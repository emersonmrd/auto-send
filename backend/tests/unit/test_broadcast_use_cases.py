import asyncio
import copy
from datetime import datetime, timedelta, timezone

import pytest
from src.application.create_broadcast_use_case import (
    CreateBroadcastCommand,
    CreateBroadcastUseCase,
    PollSpec,
)
from src.application.dispatch_broadcast_use_case import DispatchBroadcastUseCase
from src.application.errors import (
    BroadcastAbortedError,
    BroadcastNotFoundError,
    InvalidScheduleFormatError,
    ProfileNotFoundError,
)
from src.application.update_broadcast_use_case import UpdateBroadcastCommand, UpdateBroadcastUseCase
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastStatus,
    ChannelDeliveryResult,
    DeliveryFailureCategory,
    MediaAttachment,
    MediaType,
)
from src.domain.channels.channel import Channel, ChatType
from src.domain.ports.broadcast_scheduler import IBroadcastScheduler
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.infrastructure.in_memory_broadcast_repository import InMemoryBroadcastRepository
from src.infrastructure.in_memory_repositories import InMemoryChannelRepository, InMemoryProfileRepository

TOKEN = "123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
CHANNEL_ID = "-1001111111111"
GROUP_ID = "-1002222222222"
FORUM_ID = "-1003333333333"
LEGACY_ID = "-1004444444444"
PUBLIC_POLL_DETAIL = r"^Non-anonymous polls can only be sent when every destination is a group$"


class CopyingBroadcastRepository(InMemoryBroadcastRepository):
    """Guarda e devolve cópias, como o SQLite: ler de volta só mostra o que o caso de uso gravou."""

    async def save(self, broadcast):
        await super().save(copy.deepcopy(broadcast))

    async def get_by_id(self, broadcast_id):
        found = await super().get_by_id(broadcast_id)
        return copy.deepcopy(found)


class FakeScheduler(IBroadcastScheduler):
    def __init__(self):
        self.scheduled: list[tuple[str, datetime]] = []

    def schedule_broadcast(self, broadcast_id: str, run_date: datetime) -> str:
        self.scheduled.append((broadcast_id, run_date))
        return f"broadcast_{broadcast_id}"

    def reschedule_broadcast(self, broadcast_id: str, new_run_date: datetime) -> None:
        self.scheduled.append((broadcast_id, new_run_date))


@pytest.fixture
async def ctx():
    profiles = InMemoryProfileRepository()
    channels = InMemoryChannelRepository()
    broadcasts = CopyingBroadcastRepository()
    await profiles.save(Profile(id="p-1", name="Acme", credentials=BotCredentials(token=TOKEN, bot_username="acme_bot")))
    for id_, chat_id, kind, forum in [
        ("c-1", CHANNEL_ID, ChatType.CHANNEL, False),
        ("c-2", GROUP_ID, ChatType.SUPERGROUP, False),
        ("c-3", FORUM_ID, ChatType.SUPERGROUP, True),
        ("c-4", LEGACY_ID, None, False),
    ]:
        await channels.save(Channel(id=id_, profile_id="p-1", title=id_, chat_id=chat_id, chat_type=kind, is_forum=forum))
    return profiles, channels, broadcasts, FakeScheduler()


def create(ctx):
    profiles, channels, broadcasts, scheduler = ctx
    return CreateBroadcastUseCase(profiles, channels, broadcasts, scheduler)


def command(**overrides):
    fields = {"profile_id": "p-1", "target_channel_ids": [CHANNEL_ID], "text": "Olá"}
    fields.update(overrides)
    return CreateBroadcastCommand(**fields)


def public_poll(**overrides):
    fields = {"question": "Qual?", "options": ["A", "B"], "is_anonymous": False}
    fields.update(overrides)
    return PollSpec(**fields)


async def no_media():
    return None


def future(days: int = 3) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat().replace("+00:00", "Z")


# --- CreateBroadcastUseCase ---


async def test_create_saves_a_pending_broadcast_with_sanitized_text_and_button(ctx):
    b = await create(ctx).execute(
        command(text="<b>oi</b> & tchau", button_text="Ver", button_url="https://example.com"), no_media
    )

    assert b.status is BroadcastStatus.PENDING
    assert (b.text, b.button.text, b.button.url) == ("<b>oi</b> &amp; tchau", "Ver", "https://example.com")
    assert (await ctx[2].get_by_id(b.id)) is not None
    assert ctx[3].scheduled == []


async def test_create_with_future_date_schedules_in_utc(ctx):
    at = future()
    b = await create(ctx).execute(command(scheduled_at=at), no_media)

    assert b.status is BroadcastStatus.SCHEDULED
    assert b.scheduled_at.tzinfo is timezone.utc
    assert ctx[3].scheduled == [(b.id, b.scheduled_at)]


async def test_create_treats_a_date_without_timezone_as_utc(ctx):
    naive = (datetime.now(timezone.utc) + timedelta(days=2)).replace(tzinfo=None, microsecond=0)
    b = await create(ctx).execute(command(scheduled_at=naive.isoformat()), no_media)
    assert b.scheduled_at == naive.replace(tzinfo=timezone.utc)


async def test_create_converts_an_offset_date_to_utc(ctx):
    local = (datetime.now(timezone(timedelta(hours=-3))) + timedelta(days=2)).replace(microsecond=0)
    b = await create(ctx).execute(command(scheduled_at=local.isoformat()), no_media)
    assert b.scheduled_at == local.astimezone(timezone.utc)
    assert b.scheduled_at.tzinfo is timezone.utc


async def test_create_ignores_a_blank_schedule(ctx):
    b = await create(ctx).execute(command(scheduled_at="   "), no_media)
    assert (b.status, b.scheduled_at) == (BroadcastStatus.PENDING, None)


@pytest.mark.parametrize("raw", ["amanhã", "45/13/2026 99:00"])
async def test_create_rejects_an_invalid_date(ctx, raw):
    with pytest.raises(InvalidScheduleFormatError, match=r"^Invalid scheduled_at ISO-8601 format$"):
        await create(ctx).execute(command(scheduled_at=raw), no_media)


async def test_create_rejects_a_past_date(ctx):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match=r"^scheduled_at cannot be in the past$"):
        await create(ctx).execute(command(scheduled_at=past), no_media)


async def test_create_requires_the_profile_and_does_not_load_media(ctx):
    loaded = []

    async def media():
        loaded.append(True)
        return None

    with pytest.raises(ProfileNotFoundError):
        await create(ctx).execute(command(profile_id="p-x"), media)
    assert loaded == []


async def test_create_rejects_an_invalid_button_before_loading_media(ctx):
    loaded = []

    async def media():
        loaded.append(True)
        return None

    with pytest.raises(ValueError):
        await create(ctx).execute(command(button_text="Ver", button_url="http://example.com"), media)
    assert loaded == []


async def test_create_with_only_one_button_field_has_no_button(ctx):
    b = await create(ctx).execute(command(button_text="Ver"), no_media)
    assert b.button is None


async def test_create_attaches_the_loaded_media(ctx):
    attachment = MediaAttachment(file_path="/tmp/x.jpg", media_type=MediaType.PHOTO, file_size=10)

    async def media():
        return attachment

    b = await create(ctx).execute(command(), media)
    assert b.media is attachment


async def test_create_rejects_media_together_with_a_poll(ctx):
    with pytest.raises(ValueError, match=r"^A broadcast cannot have both media and a poll$"):
        await create(ctx).execute(command(has_media=True, poll=public_poll(is_anonymous=True)), no_media)


async def test_create_builds_the_poll_from_the_spec(ctx):
    spec = PollSpec(
        question=" Quanto é 1+1? ",
        options=[" 1 ", "2"],
        poll_type="QUIZ",
        correct_option_id=1,
        explanation="  dois  ",
        is_closed=True,
    )
    b = await create(ctx).execute(command(poll=spec), no_media)

    p = b.poll
    assert (p.question, p.options, p.poll_type.value, p.correct_option_id, p.explanation, p.is_closed) == (
        "Quanto é 1+1?", ["1", "2"], "quiz", 1, "dois", True
    )
    assert (p.is_anonymous, p.allows_multiple_answers) == (True, False)


async def test_create_drops_a_blank_explanation_and_defaults_to_regular(ctx):
    b = await create(ctx).execute(
        command(poll=PollSpec(question="Q?", options=["A", "B"], explanation="   ", poll_type="qualquer")), no_media
    )
    assert (b.poll.explanation, b.poll.poll_type.value) == (None, "regular")


async def test_create_rejects_an_invalid_poll(ctx):
    with pytest.raises(ValueError, match=r"^poll must have at least 2 options$"):
        await create(ctx).execute(command(poll=PollSpec(question="Q?", options=["A"])), no_media)


@pytest.mark.parametrize("targets", [[GROUP_ID], [GROUP_ID, FORUM_ID]])
async def test_public_poll_goes_to_groups(ctx, targets):
    b = await create(ctx).execute(command(target_channel_ids=targets, poll=public_poll()), no_media)
    assert b.poll.is_anonymous is False


@pytest.mark.parametrize(
    "targets",
    [[CHANNEL_ID], [GROUP_ID, CHANNEL_ID], [LEGACY_ID], [GROUP_ID, "-1009999999999"]],
    ids=["channel", "group-and-channel", "channel-without-kind", "chat-not-linked"],
)
async def test_public_poll_is_refused_unless_every_destination_is_a_known_group(ctx, targets):
    with pytest.raises(ValueError, match=PUBLIC_POLL_DETAIL):
        await create(ctx).execute(command(target_channel_ids=targets, poll=public_poll()), no_media)
    assert await ctx[2].list_by_profile("p-1") == []


async def test_public_poll_does_not_use_groups_of_another_profile(ctx):
    profiles, channels, _, _ = ctx
    await profiles.save(Profile(id="p-2", name="Outro", credentials=BotCredentials(token=TOKEN, bot_username="outro_bot")))
    await channels.save(Channel(id="c-9", profile_id="p-2", title="G", chat_id="-1005555555555", chat_type=ChatType.SUPERGROUP))

    with pytest.raises(ValueError, match=PUBLIC_POLL_DETAIL):
        await create(ctx).execute(command(target_channel_ids=["-1005555555555"], poll=public_poll()), no_media)


async def test_anonymous_poll_goes_to_channels(ctx):
    b = await create(ctx).execute(command(target_channel_ids=[CHANNEL_ID, LEGACY_ID], poll=public_poll(is_anonymous=True)), no_media)
    assert b.poll.is_anonymous is True


# --- DispatchBroadcastUseCase ---


class RecordingObserver:
    def __init__(self, stop_after: int | None = None):
        self.stop_after = stop_after
        self.checks = 0
        self.done: list[tuple[int, int]] = []
        self.upload_callbacks = 0

    async def should_stop(self) -> bool:
        self.checks += 1
        return self.stop_after is not None and self.checks > self.stop_after

    def upload_progress_callback(self):
        self.upload_callbacks += 1
        return lambda sent, total: None

    def channel_done(self, done: int, total: int) -> None:
        self.done.append((done, total))


def sender(outcomes: dict, uploaded_file_id: str | None = None):
    calls: list[tuple] = []

    async def send(chat_id, progress_callback, file_id):
        calls.append((chat_id, progress_callback is not None, file_id))
        ok = outcomes.get(chat_id, True)
        if isinstance(ok, BaseException):
            raise ok
        if ok:
            return ChannelDeliveryResult.success(chat_id), None, uploaded_file_id
        res = ChannelDeliveryResult.failure(chat_id, category=DeliveryFailureCategory.OTHER, detail="recusado")
        return res, f"Failed to send to {chat_id}: recusado", None

    return send, calls


async def pending(ctx, targets, media=None) -> BroadcastMessage:
    b = BroadcastMessage(id="b-1", profile_id="p-1", target_channel_ids=targets, text="Oi", media=media)
    await ctx[2].save(b)
    return b


async def test_dispatch_sends_to_each_channel_and_records_results(ctx):
    b = await pending(ctx, [CHANNEL_ID, GROUP_ID])
    send, calls = sender({GROUP_ID: False})
    observer = RecordingObserver()

    outcome = await DispatchBroadcastUseCase(ctx[2]).execute(b, send, observer)

    assert calls == [(CHANNEL_ID, False, None), (GROUP_ID, False, None)]
    assert (outcome.dispatched_count, outcome.errors) == (1, [f"Failed to send to {GROUP_ID}: recusado"])
    assert observer.done == [(1, 2), (2, 2)]
    saved = await ctx[2].get_by_id("b-1")
    assert saved.status is BroadcastStatus.PARTIALLY_COMPLETED
    assert [r.delivered for r in saved.delivery_results] == [True, False]


async def test_dispatch_with_media_uploads_once_and_reuses_the_file_id(ctx):
    media = MediaAttachment(file_path="/tmp/v.mp4", media_type=MediaType.VIDEO, file_size=10)
    b = await pending(ctx, [CHANNEL_ID, GROUP_ID, FORUM_ID], media=media)
    send, calls = sender({}, uploaded_file_id="file-abc")
    observer = RecordingObserver()

    await DispatchBroadcastUseCase(ctx[2]).execute(b, send, observer)

    assert calls == [(CHANNEL_ID, True, None), (GROUP_ID, False, "file-abc"), (FORUM_ID, False, "file-abc")]
    assert observer.upload_callbacks == 1
    # Com mídia, o progresso vem do upload, não da contagem de canais.
    assert observer.done == []


async def test_dispatch_keeps_uploading_until_one_channel_accepts_the_media(ctx):
    media = MediaAttachment(file_path="/tmp/v.mp4", media_type=MediaType.VIDEO, file_size=10)
    b = await pending(ctx, [CHANNEL_ID, GROUP_ID], media=media)
    send, calls = sender({CHANNEL_ID: False}, uploaded_file_id="file-abc")

    await DispatchBroadcastUseCase(ctx[2]).execute(b, send, RecordingObserver())

    assert calls == [(CHANNEL_ID, True, None), (GROUP_ID, True, None)]


async def test_dispatch_stopped_by_the_user_keeps_partial_deliveries(ctx):
    b = await pending(ctx, [CHANNEL_ID, GROUP_ID])
    send, calls = sender({})

    with pytest.raises(BroadcastAbortedError, match=r"^Broadcast cancelled by user$"):
        await DispatchBroadcastUseCase(ctx[2]).execute(b, send, RecordingObserver(stop_after=1))

    assert [c[0] for c in calls] == [CHANNEL_ID]
    saved = await ctx[2].get_by_id("b-1")
    assert saved.status is BroadcastStatus.CANCELLED
    assert [r.chat_id for r in saved.delivery_results] == [CHANNEL_ID]


async def test_dispatch_cancelled_mid_upload_is_aborted(ctx):
    b = await pending(ctx, [CHANNEL_ID])
    send, _ = sender({CHANNEL_ID: asyncio.CancelledError()})

    with pytest.raises(BroadcastAbortedError):
        await DispatchBroadcastUseCase(ctx[2]).execute(b, send, RecordingObserver())
    assert (await ctx[2].get_by_id("b-1")).status is BroadcastStatus.CANCELLED


async def test_dispatch_lets_unexpected_errors_through(ctx):
    b = await pending(ctx, [CHANNEL_ID])
    send, _ = sender({CHANNEL_ID: RuntimeError("bug")})

    with pytest.raises(RuntimeError):
        await DispatchBroadcastUseCase(ctx[2]).execute(b, send, RecordingObserver())


# --- UpdateBroadcastUseCase ---


async def scheduled(ctx, targets, poll=None) -> BroadcastMessage:
    from src.domain.broadcast.broadcast_message import BroadcastPoll

    b = BroadcastMessage(
        id="b-1",
        profile_id="p-1",
        target_channel_ids=targets,
        text="Oi" if poll is None else "",
        poll=BroadcastPoll(question="Q?", options=["A", "B"], is_anonymous=False) if poll == "public" else None,
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=3),
        status=BroadcastStatus.SCHEDULED,
    )
    await ctx[2].save(b)
    return b


def update(ctx):
    _, channels, broadcasts, scheduler = ctx
    return UpdateBroadcastUseCase(channels, broadcasts, scheduler)


async def test_update_changes_text_button_and_reschedules(ctx):
    await scheduled(ctx, [CHANNEL_ID])
    at = future(5)

    b = await update(ctx).execute(
        UpdateBroadcastCommand(broadcast_id="b-1", text="Novo", button_text="Ver", button_url="https://example.com", scheduled_at=at)
    )

    assert (b.text, b.button.url) == ("Novo", "https://example.com")
    assert ctx[3].scheduled == [("b-1", b.scheduled_at)]
    assert b.scheduled_at == datetime.fromisoformat(at.replace("Z", "+00:00"))


async def test_update_with_empty_button_fields_removes_the_button(ctx):
    b = await scheduled(ctx, [CHANNEL_ID])
    from src.domain.broadcast.broadcast_message import InlineButton

    b.update_content(text="Oi", button=InlineButton(text="Ver", url="https://example.com"))
    await ctx[2].save(b)

    b = await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", button_text="", button_url=""))
    assert b.button is None


@pytest.mark.parametrize("text, url", [("Ver", None), (None, "https://example.com"), ("  ", "https://example.com")])
async def test_update_requires_both_button_fields(ctx, text, url):
    await scheduled(ctx, [CHANNEL_ID])
    with pytest.raises(ValueError, match=r"^Both button_text and button_url are required when defining an inline button$"):
        await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", button_text=text, button_url=url))


async def test_update_rejects_unknown_broadcast(ctx):
    with pytest.raises(BroadcastNotFoundError):
        await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-x"))


async def test_update_rejects_a_broadcast_already_sent(ctx):
    b = await scheduled(ctx, [CHANNEL_ID])
    b.status = BroadcastStatus.COMPLETED
    await ctx[2].save(b)
    with pytest.raises(ValueError, match=r"^Cannot edit an in-flight, completed, or cancelled broadcast$"):
        await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", text="X"))


async def test_update_rejects_invalid_and_past_dates(ctx):
    await scheduled(ctx, [CHANNEL_ID])
    with pytest.raises(InvalidScheduleFormatError):
        await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", scheduled_at="ontem"))
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match=r"^scheduled_at cannot be in the past$"):
        await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", scheduled_at=past))


async def test_saving_an_edit_lock_without_new_date_after_the_time_passed_requires_a_future_date(ctx):
    b = await scheduled(ctx, [CHANNEL_ID])
    now = datetime.now(timezone.utc)
    b.acquire_edit_lock(now=now)
    b.scheduled_at = now - timedelta(minutes=1)
    await ctx[2].save(b)

    with pytest.raises(ValueError, match=r"^scheduled_at cannot be in the past$"):
        await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", text="X"))


async def test_saving_an_edit_lock_releases_it_and_restores_the_job(ctx):
    b = await scheduled(ctx, [CHANNEL_ID])
    b.acquire_edit_lock(now=datetime.now(timezone.utc))
    await ctx[2].save(b)

    b = await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", text="X"))

    assert b.edit_locked_until is None
    assert ctx[3].scheduled == [("b-1", b.scheduled_at)]


async def test_update_without_lock_or_date_does_not_touch_the_job(ctx):
    await scheduled(ctx, [CHANNEL_ID])
    await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", text="X"))
    assert ctx[3].scheduled == []


async def test_update_can_retarget_a_public_poll_to_other_groups(ctx):
    await scheduled(ctx, [GROUP_ID], poll="public")
    b = await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", target_channel_ids=[FORUM_ID]))
    assert b.target_channel_ids == [FORUM_ID]


async def test_update_refuses_adding_a_channel_to_a_public_poll(ctx):
    await scheduled(ctx, [GROUP_ID], poll="public")
    with pytest.raises(ValueError, match=PUBLIC_POLL_DETAIL):
        await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", target_channel_ids=[GROUP_ID, CHANNEL_ID]))
    assert (await ctx[2].get_by_id("b-1")).target_channel_ids == [GROUP_ID]


async def test_update_retargets_a_broadcast_without_poll_to_any_chat(ctx):
    await scheduled(ctx, [GROUP_ID])
    b = await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", target_channel_ids=[CHANNEL_ID, LEGACY_ID]))
    assert b.target_channel_ids == [CHANNEL_ID, LEGACY_ID]


async def test_dispatch_failure_without_legacy_message_adds_no_error(ctx):
    b = await pending(ctx, [CHANNEL_ID])

    async def send(chat_id, progress_callback, file_id):
        return ChannelDeliveryResult.failure(chat_id, category=DeliveryFailureCategory.OTHER, detail=None), None, None

    outcome = await DispatchBroadcastUseCase(ctx[2]).execute(b, send, RecordingObserver())
    assert (outcome.dispatched_count, outcome.errors) == (0, [])


async def test_saving_an_edit_lock_of_a_misfired_broadcast_releases_it_without_rescheduling(ctx):
    b = await scheduled(ctx, [CHANNEL_ID])
    b.acquire_edit_lock(now=datetime.now(timezone.utc))
    b.mark_misfired()
    await ctx[2].save(b)

    b = await update(ctx).execute(UpdateBroadcastCommand(broadcast_id="b-1", text="X"))

    assert (b.edit_locked_until, b.status) == (None, BroadcastStatus.MISFIRED)
    assert ctx[3].scheduled == []



async def test_editing_only_the_text_of_an_existing_public_poll_still_works(ctx):
    # Enquete pública de antes da #99 (criada pela API, ou para canal ainda sem tipo): o modo edição
    # sempre manda os destinos; se eles não mudaram, a regra não pode travar a edição.
    await scheduled(ctx, [LEGACY_ID, CHANNEL_ID], poll="public")

    b = await update(ctx).execute(
        UpdateBroadcastCommand(broadcast_id="b-1", text="Novo", target_channel_ids=[CHANNEL_ID, LEGACY_ID])
    )

    assert (b.text, b.target_channel_ids) == ("Novo", [CHANNEL_ID, LEGACY_ID])
    assert (await ctx[2].get_by_id("b-1")).text == "Novo"
