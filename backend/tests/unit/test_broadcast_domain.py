from datetime import datetime, timezone
import pytest
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastStatus,
    DispatchStrategy,
    InlineButton,
    MediaAttachment,
    MediaType,
)

def test_should_choose_single_message_strategy_when_text_le_1024_and_has_media():
    button = InlineButton(text="Learn more", url="https://t.me/news")
    media = MediaAttachment(file_path="/tmp/video.mp4", media_type=MediaType.VIDEO, file_size=1024)
    
    msg = BroadcastMessage(
        id="broadcast-1",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="A" * 500,
        media=media,
        button=button,
    )
    
    assert msg.get_dispatch_strategy() == DispatchStrategy.SINGLE_MEDIA_WITH_CAPTION
    assert msg.status == BroadcastStatus.PENDING

def test_should_choose_single_message_strategy_at_exact_1024_boundary():
    media = MediaAttachment(file_path="/tmp/video.mp4", media_type=MediaType.VIDEO, file_size=1024)
    msg = BroadcastMessage(
        id="broadcast-boundary",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="A" * 1024,
        media=media,
    )
    assert msg.get_dispatch_strategy() == DispatchStrategy.SINGLE_MEDIA_WITH_CAPTION

def test_should_choose_split_message_strategy_when_text_gt_1024_and_has_media():
    media = MediaAttachment(file_path="/tmp/video.mp4", media_type=MediaType.VIDEO, file_size=1024)
    
    msg = BroadcastMessage(
        id="broadcast-2",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="A" * 1025,
        media=media,
    )
    
    assert msg.get_dispatch_strategy() == DispatchStrategy.SPLIT_TEXT_THEN_MEDIA

def test_should_choose_text_only_strategy_when_no_media():
    msg = BroadcastMessage(
        id="broadcast-3",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="A" * 200,
    )
    
    assert msg.get_dispatch_strategy() == DispatchStrategy.TEXT_ONLY

def test_should_reject_button_url_with_private_or_unsafe_protocols():
    with pytest.raises(ValueError, match="Insecure or invalid URL scheme"):
        InlineButton(text="Click", url="http://127.0.0.1:8000/admin")
        
    with pytest.raises(ValueError, match="Insecure or invalid URL scheme"):
        InlineButton(text="Click", url="file:///etc/passwd")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme"):
        InlineButton(text="Click", url="http://google.com")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme: Private network prohibited"):
        InlineButton(text="Click", url="https://localhost/api")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme: Private network prohibited"):
        InlineButton(text="Click", url="https://127.0.0.1/api")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme: Private network prohibited"):
        InlineButton(text="Click", url="https://0.0.0.0/api")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme: Private IP prohibited"):
        InlineButton(text="Click", url="https://192.168.1.1/api")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme: Private IP prohibited"):
        InlineButton(text="Click", url="https://10.0.0.1/api")

def test_should_accept_valid_public_https_button_url():
    btn = InlineButton(text="Join", url="https://t.me/+joinlink")
    assert btn.text == "Join"
    assert btn.url == "https://t.me/+joinlink"

def test_cancel_broadcast_lifecycle():
    msg = BroadcastMessage(
        id="b-1",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.PENDING,
    )
    msg.cancel()
    assert msg.status == BroadcastStatus.CANCELLED

    msg_scheduled = BroadcastMessage(
        id="b-2",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.SCHEDULED,
    )
    msg_scheduled.cancel()
    assert msg_scheduled.status == BroadcastStatus.CANCELLED

    msg_dispatching = BroadcastMessage(
        id="b-3",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.DISPATCHING,
    )
    with pytest.raises(ValueError, match="Cannot cancel an in-flight or completed broadcast"):
        msg_dispatching.cancel()

    msg_completed = BroadcastMessage(
        id="b-4",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.COMPLETED,
    )
    with pytest.raises(ValueError, match="Cannot cancel an in-flight or completed broadcast"):
        msg_completed.cancel()

def test_reschedule_broadcast_lifecycle():
    now = datetime.now(timezone.utc)
    new_date = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
    
    msg_pending = BroadcastMessage(
        id="b-5",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.PENDING,
        scheduled_at=now,
    )
    msg_pending.reschedule(new_date)
    assert msg_pending.scheduled_at == new_date
    assert msg_pending.status == BroadcastStatus.SCHEDULED

    msg_scheduled = BroadcastMessage(
        id="b-6",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.SCHEDULED,
        scheduled_at=now,
    )
    msg_scheduled.reschedule(new_date)
    assert msg_scheduled.scheduled_at == new_date
    assert msg_scheduled.status == BroadcastStatus.SCHEDULED

    for invalid_status in [BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED, BroadcastStatus.CANCELLED]:
        msg_invalid = BroadcastMessage(
            id="b-inv",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Hello",
            status=invalid_status,
        )
        with pytest.raises(ValueError, match="Cannot reschedule an in-flight, completed, or cancelled broadcast"):
            msg_invalid.reschedule(new_date)

def test_update_content_broadcast_lifecycle():
    msg = BroadcastMessage(
        id="b-7",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Initial text",
        status=BroadcastStatus.PENDING,
    )
    new_button = InlineButton(text="Updated", url="https://t.me/updated")
    msg.update_content("Updated text", new_button)
    assert msg.text == "Updated text"
    assert msg.button == new_button

    msg.update_content("Only text updated", None)
    assert msg.text == "Only text updated"
    assert msg.button is None

    for invalid_status in [BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED, BroadcastStatus.CANCELLED]:
        msg_invalid = BroadcastMessage(
            id="b-inv-upd",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Hello",
            status=invalid_status,
        )
        with pytest.raises(ValueError, match="Cannot update content of an in-flight, completed, or cancelled broadcast"):
            msg_invalid.update_content("New text")

@pytest.mark.asyncio
async def test_in_memory_repository_get_scheduled_by_profile():
    from src.infrastructure.in_memory_broadcast_repository import InMemoryBroadcastRepository
    
    repo = InMemoryBroadcastRepository()
    d1 = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    d3 = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)

    # b1: profile-1, SCHEDULED, d1
    b1 = BroadcastMessage(id="b1", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.SCHEDULED, scheduled_at=d1)
    # b2: profile-1, PENDING, d2 (earlier)
    b2 = BroadcastMessage(id="b2", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.PENDING, scheduled_at=d2)
    # b3: profile-1, CANCELLED, d3 (should be excluded)
    b3 = BroadcastMessage(id="b3", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.CANCELLED, scheduled_at=d3)
    # b4: profile-1, COMPLETED (should be excluded)
    b4 = BroadcastMessage(id="b4", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.COMPLETED, scheduled_at=d1)
    # b5: profile-2, SCHEDULED, d2 (different profile)
    b5 = BroadcastMessage(id="b5", profile_id="m2", target_channel_ids=["-1001"], status=BroadcastStatus.SCHEDULED, scheduled_at=d2)
    # b6: profile-1, SCHEDULED, scheduled_at is None (should be excluded)
    b6 = BroadcastMessage(id="b6", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.SCHEDULED, scheduled_at=None)

    for b in [b1, b2, b3, b4, b5, b6]:
        await repo.save(b)

    scheduled_m1 = await repo.get_scheduled_by_profile("m1")
    assert len(scheduled_m1) == 2
    # Deve ser ordenado ascendentemente por scheduled_at: b2 (d2: 10:00) depois b1 (d1: 12:00)
    assert scheduled_m1[0].id == "b2"
    assert scheduled_m1[1].id == "b1"


def _dispatching_broadcast(targets: int) -> BroadcastMessage:
    ids = [f"-100123456789{i}" for i in range(targets)]
    return BroadcastMessage(id="b", profile_id="p", target_channel_ids=ids, status=BroadcastStatus.DISPATCHING)


def test_finish_dispatch_completes_when_every_channel_received():
    msg = _dispatching_broadcast(3)
    msg.finish_dispatch(delivered=3, total=3)
    assert msg.status is BroadcastStatus.COMPLETED


def test_finish_dispatch_is_partial_when_some_channels_received():
    msg = _dispatching_broadcast(3)
    msg.finish_dispatch(delivered=1, total=3)
    assert msg.status is BroadcastStatus.PARTIALLY_COMPLETED
    msg = _dispatching_broadcast(3)
    msg.finish_dispatch(delivered=2, total=3)
    assert msg.status is BroadcastStatus.PARTIALLY_COMPLETED


def test_finish_dispatch_fails_when_no_channel_received():
    msg = _dispatching_broadcast(3)
    msg.finish_dispatch(delivered=0, total=3)
    assert msg.status is BroadcastStatus.FAILED


def test_finish_dispatch_rejects_impossible_counts():
    with pytest.raises(ValueError, match=r"^delivered must be between 0 and total$"):
        _dispatching_broadcast(2).finish_dispatch(delivered=3, total=2)
    with pytest.raises(ValueError, match=r"^delivered must be between 0 and total$"):
        _dispatching_broadcast(2).finish_dispatch(delivered=-1, total=2)
