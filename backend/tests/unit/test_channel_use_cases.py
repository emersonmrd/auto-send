import pytest
from src.application.errors import (
    ChannelAlreadyRegisteredError,
    ChannelDispatchingError,
    ChannelNotFoundError,
    ProfileNotFoundError,
)
from src.application.register_channel_use_case import RegisterChannelCommand, RegisterChannelUseCase
from src.application.update_channel_use_case import UpdateChannelCommand, UpdateChannelUseCase
from src.domain.broadcast.broadcast_message import BroadcastMessage, BroadcastStatus
from src.domain.channels.channel import Channel, ChatType
from src.domain.channels.chat_discovery import ChatIdentifier, DiscoveredChat
from src.domain.ports.chat_discovery_gateway import (
    BotNotChannelAdminError,
    ChatDiscoveryError,
    IChatDiscoveryGateway,
)
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.infrastructure.in_memory_broadcast_repository import InMemoryBroadcastRepository
from src.infrastructure.in_memory_repositories import InMemoryChannelRepository, InMemoryProfileRepository

TOKEN = "123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
CHAT_ID = "-1001234567890"
OTHER_CHAT_ID = "-1009876543210"


class FakeGateway(IChatDiscoveryGateway):
    """Telegram de mentira: responde ao getChat com o chat configurado e registra cada chamada."""

    def __init__(self, chat: DiscoveredChat | None = None, can_post_error: Exception | None = None,
                 resolve_error: Exception | None = None):
        self.chat = chat
        self.can_post_error = can_post_error
        self.resolve_error = resolve_error
        self.calls: list[tuple] = []

    async def discover_chats(self, bot_token):
        raise AssertionError("discover_chats is not used to register a channel")

    async def resolve_chat(self, bot_token, identifier: ChatIdentifier):
        self.calls.append(("resolve", bot_token, identifier.as_chat_id()))
        if self.resolve_error:
            raise self.resolve_error
        assert self.chat is not None
        return self.chat

    async def ensure_bot_can_post(self, bot_token, chat_id):
        self.calls.append(("ensure_bot_can_post", bot_token, chat_id))
        if self.can_post_error:
            raise self.can_post_error


def forum(chat_id: str = CHAT_ID) -> DiscoveredChat:
    return DiscoveredChat(chat_id=chat_id, title="Grupo VIP", chat_type="supergroup", is_forum=True)


def channel_chat(chat_id: str = CHAT_ID) -> DiscoveredChat:
    return DiscoveredChat(chat_id=chat_id, title="Canal de Novidades", chat_type="channel")


@pytest.fixture
async def repos():
    profiles = InMemoryProfileRepository()
    await profiles.save(Profile(id="p-1", name="Acme", credentials=BotCredentials(token=TOKEN, bot_username="acme_bot")))
    return profiles, InMemoryChannelRepository(), InMemoryBroadcastRepository()


def register(repos, gateway):
    profiles, channels, _ = repos
    return RegisterChannelUseCase(profiles, channels, gateway)


def update(repos, gateway):
    profiles, channels, broadcasts = repos
    return UpdateChannelUseCase(profiles, channels, broadcasts, gateway)


# --- RegisterChannelUseCase ---


async def test_register_checks_permission_then_saves_the_kind_reported_by_telegram(repos):
    gateway = FakeGateway(chat=forum())

    channel = await register(repos, gateway).execute(
        RegisterChannelCommand(profile_id="p-1", title="Grupo VIP", chat_id=CHAT_ID, invite_link="https://t.me/+abc")
    )

    assert gateway.calls == [("ensure_bot_can_post", TOKEN, CHAT_ID), ("resolve", TOKEN, CHAT_ID)]
    assert (channel.chat_type, channel.is_forum, channel.invite_link) == (ChatType.SUPERGROUP, True, "https://t.me/+abc")
    saved = await repos[1].get_by_id(channel.id)
    assert saved is not None
    assert (saved.profile_id, saved.title, saved.chat_id, saved.chat_type) == ("p-1", "Grupo VIP", CHAT_ID, ChatType.SUPERGROUP)


async def test_register_keeps_the_channel_without_kind_when_get_chat_fails(repos):
    # A permissão já foi conferida: sem o tipo, o canal só fica sem badge.
    gateway = FakeGateway(resolve_error=ChatDiscoveryError("Telegram API error: Bad Request"))

    channel = await register(repos, gateway).execute(RegisterChannelCommand(profile_id="p-1", title="Canal", chat_id=CHAT_ID))

    assert (channel.chat_type, channel.is_forum, channel.invite_link) == (None, False, "")
    assert await repos[1].get_by_id(channel.id) is not None


async def test_register_rejects_unknown_profile_before_calling_telegram(repos):
    gateway = FakeGateway(chat=channel_chat())

    with pytest.raises(ProfileNotFoundError):
        await register(repos, gateway).execute(RegisterChannelCommand(profile_id="p-x", title="Canal", chat_id=CHAT_ID))
    assert gateway.calls == []


async def test_register_rejects_a_chat_already_linked_to_the_profile(repos):
    await repos[1].save(Channel(id="c-1", profile_id="p-1", title="Canal", chat_id=CHAT_ID))
    gateway = FakeGateway(chat=channel_chat())

    with pytest.raises(ChannelAlreadyRegisteredError, match=r"^Channel already registered for this profile$"):
        await register(repos, gateway).execute(RegisterChannelCommand(profile_id="p-1", title="Canal", chat_id=CHAT_ID))
    assert gateway.calls == []


async def test_register_rejects_an_invalid_chat_id_before_calling_telegram(repos):
    gateway = FakeGateway(chat=channel_chat())

    with pytest.raises(ValueError, match=r"^Invalid Telegram Channel Chat ID format"):
        await register(repos, gateway).execute(RegisterChannelCommand(profile_id="p-1", title="Canal", chat_id="-123456789"))
    assert gateway.calls == []


async def test_register_does_not_save_when_the_bot_cannot_post(repos):
    gateway = FakeGateway(chat=channel_chat(), can_post_error=BotNotChannelAdminError("Bot is not administrator in the channel"))

    with pytest.raises(BotNotChannelAdminError):
        await register(repos, gateway).execute(RegisterChannelCommand(profile_id="p-1", title="Canal", chat_id=CHAT_ID))
    assert await repos[1].list_by_profile("p-1") == []
    assert gateway.calls == [("ensure_bot_can_post", TOKEN, CHAT_ID)]


# --- UpdateChannelUseCase ---


async def test_update_with_new_chat_id_rechecks_permission_reclassifies_and_retargets_scheduled_broadcasts(repos):
    _, channels, broadcasts = repos
    await channels.save(Channel(id="c-1", profile_id="p-1", title="Canal", chat_id=CHAT_ID, chat_type=ChatType.CHANNEL))
    scheduled = BroadcastMessage(id="b-1", profile_id="p-1", target_channel_ids=[CHAT_ID], text="Oi")
    done = BroadcastMessage(id="b-2", profile_id="p-1", target_channel_ids=[CHAT_ID], text="Antigo")
    done.status = BroadcastStatus.COMPLETED
    await broadcasts.save(scheduled)
    await broadcasts.save(done)
    gateway = FakeGateway(chat=forum(OTHER_CHAT_ID))

    channel = await update(repos, gateway).execute(
        UpdateChannelCommand(channel_id="c-1", title="Grupo VIP", chat_id=OTHER_CHAT_ID)
    )

    assert gateway.calls == [("ensure_bot_can_post", TOKEN, OTHER_CHAT_ID), ("resolve", TOKEN, OTHER_CHAT_ID)]
    assert (channel.title, channel.chat_id, channel.chat_type, channel.is_forum) == ("Grupo VIP", OTHER_CHAT_ID, ChatType.SUPERGROUP, True)
    assert (await broadcasts.get_by_id("b-1")).target_channel_ids == [OTHER_CHAT_ID]
    assert (await broadcasts.get_by_id("b-2")).target_channel_ids == [CHAT_ID]
    saved = await channels.get_by_id("c-1")
    assert (saved.title, saved.chat_id, saved.chat_type) == ("Grupo VIP", OTHER_CHAT_ID, ChatType.SUPERGROUP)


async def test_rename_of_a_classified_channel_does_not_call_telegram(repos):
    await repos[1].save(Channel(id="c-1", profile_id="p-1", title="Canal", chat_id=CHAT_ID, chat_type=ChatType.CHANNEL))
    gateway = FakeGateway(chat=channel_chat())

    channel = await update(repos, gateway).execute(UpdateChannelCommand(channel_id="c-1", title="Novo nome", chat_id=CHAT_ID))

    assert gateway.calls == []
    assert (channel.title, channel.chat_type) == ("Novo nome", ChatType.CHANNEL)


async def test_rename_of_a_channel_linked_before_chat_types_fills_in_its_kind(repos):
    # Backfill da #99: a migração não consulta o Telegram; a próxima edição consulta.
    await repos[1].save(Channel(id="c-1", profile_id="p-1", title="Grupo", chat_id=CHAT_ID))
    gateway = FakeGateway(chat=forum())

    channel = await update(repos, gateway).execute(UpdateChannelCommand(channel_id="c-1", title="Grupo", chat_id=CHAT_ID))

    assert gateway.calls == [("resolve", TOKEN, CHAT_ID)]
    assert (channel.chat_type, channel.is_forum) == (ChatType.SUPERGROUP, True)
    assert (await repos[1].get_by_id("c-1")).chat_type is ChatType.SUPERGROUP


async def test_update_keeps_saving_when_get_chat_fails(repos):
    await repos[1].save(Channel(id="c-1", profile_id="p-1", title="Grupo", chat_id=CHAT_ID))
    gateway = FakeGateway(resolve_error=ChatDiscoveryError("Telegram unreachable (ConnectError)"))

    channel = await update(repos, gateway).execute(UpdateChannelCommand(channel_id="c-1", title="Outro", chat_id=CHAT_ID))

    assert (channel.title, channel.chat_type) == ("Outro", None)
    assert (await repos[1].get_by_id("c-1")).title == "Outro"


async def test_update_rejects_unknown_channel(repos):
    with pytest.raises(ChannelNotFoundError):
        await update(repos, FakeGateway()).execute(UpdateChannelCommand(channel_id="c-x", title="X", chat_id=CHAT_ID))


async def test_update_rejects_an_invalid_chat_id_without_changing_the_channel(repos):
    await repos[1].save(Channel(id="c-1", profile_id="p-1", title="Canal", chat_id=CHAT_ID, chat_type=ChatType.CHANNEL))
    gateway = FakeGateway(chat=channel_chat())

    with pytest.raises(ValueError, match=r"^Invalid Telegram Channel Chat ID format"):
        await update(repos, gateway).execute(UpdateChannelCommand(channel_id="c-1", title="X", chat_id="-123456789"))
    assert gateway.calls == []
    assert (await repos[1].get_by_id("c-1")).chat_id == CHAT_ID


async def test_update_rejects_a_chat_id_used_by_another_channel_of_the_profile(repos):
    await repos[1].save(Channel(id="c-1", profile_id="p-1", title="A", chat_id=CHAT_ID))
    await repos[1].save(Channel(id="c-2", profile_id="p-1", title="B", chat_id=OTHER_CHAT_ID))

    with pytest.raises(ChannelAlreadyRegisteredError):
        await update(repos, FakeGateway()).execute(UpdateChannelCommand(channel_id="c-1", title="A", chat_id=OTHER_CHAT_ID))


async def test_update_rejects_a_new_chat_id_while_a_broadcast_is_dispatching_to_it(repos):
    _, channels, broadcasts = repos
    await channels.save(Channel(id="c-1", profile_id="p-1", title="A", chat_id=CHAT_ID))
    dispatching = BroadcastMessage(id="b-1", profile_id="p-1", target_channel_ids=[CHAT_ID], text="Oi")
    dispatching.status = BroadcastStatus.DISPATCHING
    await broadcasts.save(dispatching)
    gateway = FakeGateway(chat=channel_chat(OTHER_CHAT_ID))

    with pytest.raises(ChannelDispatchingError, match=r"^There is a broadcast currently dispatching\. Wait for it to finish and try again\.$"):
        await update(repos, gateway).execute(UpdateChannelCommand(channel_id="c-1", title="A", chat_id=OTHER_CHAT_ID))
    assert gateway.calls == []


async def test_update_with_new_chat_id_requires_the_profile(repos):
    await repos[1].save(Channel(id="c-1", profile_id="p-orfao", title="A", chat_id=CHAT_ID))

    with pytest.raises(ProfileNotFoundError):
        await update(repos, FakeGateway()).execute(UpdateChannelCommand(channel_id="c-1", title="A", chat_id=OTHER_CHAT_ID))


async def test_update_does_not_save_when_the_bot_cannot_post_in_the_new_chat(repos):
    await repos[1].save(Channel(id="c-1", profile_id="p-1", title="A", chat_id=CHAT_ID))
    gateway = FakeGateway(can_post_error=BotNotChannelAdminError("Bot is not administrator in the channel"))

    with pytest.raises(BotNotChannelAdminError):
        await update(repos, gateway).execute(UpdateChannelCommand(channel_id="c-1", title="B", chat_id=OTHER_CHAT_ID))
    saved = await repos[1].get_by_id("c-1")
    assert (saved.title, saved.chat_id) == ("A", CHAT_ID)


async def test_rename_of_a_channel_without_kind_whose_profile_is_gone_saves_without_telegram(repos):
    await repos[1].save(Channel(id="c-1", profile_id="p-orfao", title="Grupo", chat_id=CHAT_ID))
    gateway = FakeGateway(chat=forum())

    channel = await update(repos, gateway).execute(UpdateChannelCommand(channel_id="c-1", title="Outro", chat_id=CHAT_ID))

    assert gateway.calls == []
    assert (channel.title, channel.chat_type) == ("Outro", None)


async def test_relink_persists_nothing_when_get_chat_fails_unexpectedly(repos):
    # Toda chamada ao Telegram roda antes de qualquer gravação: um erro no getChat não deixa
    # broadcasts apontando para um chat que o canal não tem.
    _, channels, broadcasts = repos
    await channels.save(Channel(id="c-1", profile_id="p-1", title="A", chat_id=CHAT_ID))
    await broadcasts.save(BroadcastMessage(id="b-1", profile_id="p-1", target_channel_ids=[CHAT_ID], text="Oi"))
    gateway = FakeGateway(resolve_error=RuntimeError("falha inesperada"))

    with pytest.raises(RuntimeError):
        await update(repos, gateway).execute(UpdateChannelCommand(channel_id="c-1", title="A", chat_id=OTHER_CHAT_ID))
    assert (await broadcasts.get_by_id("b-1")).target_channel_ids == [CHAT_ID]


async def test_register_channel_with_forum_topic(repos):
    # Issue #101: cadastro de canal com tópico de fórum
    gateway = FakeGateway(chat=forum())
    channel = await register(repos, gateway).execute(
        RegisterChannelCommand(
            profile_id="p-1",
            title="Grupo VIP (#Anúncios)",
            chat_id=CHAT_ID,
            message_thread_id=45,
            topic_name="Anúncios",
        )
    )
    assert channel.message_thread_id == 45
    assert channel.topic_name == "Anúncios"
    assert channel.destination_id == f"{CHAT_ID}:45"


async def test_register_multiple_topics_of_same_forum_group(repos):
    # Issue #101: permite cadastrar múltiplos tópicos diferentes do mesmo supergrupo
    gateway = FakeGateway(chat=forum())
    c1 = await register(repos, gateway).execute(
        RegisterChannelCommand(profile_id="p-1", title="Grupo Geral", chat_id=CHAT_ID)
    )
    c2 = await register(repos, gateway).execute(
        RegisterChannelCommand(profile_id="p-1", title="Grupo Anúncios", chat_id=CHAT_ID, message_thread_id=45, topic_name="Anúncios")
    )
    assert c1.chat_id == c2.chat_id
    assert c1.message_thread_id is None
    assert c2.message_thread_id == 45

    # Tentar cadastrar exatamente o mesmo tópico 45 novamente falha
    with pytest.raises(ChannelAlreadyRegisteredError):
        await register(repos, gateway).execute(
            RegisterChannelCommand(profile_id="p-1", title="Duplicado", chat_id=CHAT_ID, message_thread_id=45)
        )


async def test_update_channel_topic(repos):
    # Issue #101: atualiza tópico de um canal existente
    await repos[1].save(Channel(id="c-1", profile_id="p-1", title="Grupo", chat_id=CHAT_ID, chat_type=ChatType.SUPERGROUP, is_forum=True))
    gateway = FakeGateway(chat=forum())

    updated = await update(repos, gateway).execute(
        UpdateChannelCommand(channel_id="c-1", title="Grupo (#Geral)", chat_id=CHAT_ID, message_thread_id=10, topic_name="Geral")
    )
    assert updated.message_thread_id == 10
    assert updated.topic_name == "Geral"
