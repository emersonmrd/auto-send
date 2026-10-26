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
    d4 = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)

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
    # b7: profile-1, MISFIRED, d4 (deve aparecer primeiro na fila antes dos SCHEDULED/PENDING)
    b7 = BroadcastMessage(id="b7", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.MISFIRED, scheduled_at=d4)

    for b in [b1, b2, b3, b4, b5, b6, b7]:
        await repo.save(b)

    scheduled_m1 = await repo.get_scheduled_by_profile("m1")
    assert [b.id for b in scheduled_m1] == ["b7", "b2", "b1"]


def test_misfired_transitions_and_guards():
    now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    future = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)

    for valid_status in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED):
        msg = BroadcastMessage(
            id="b-m",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Bom dia",
            status=valid_status,
            scheduled_at=now,
        )
        msg.mark_misfired()
        assert msg.status is BroadcastStatus.MISFIRED

    # De MISFIRED -> SCHEDULED via reschedule, podendo editar conteúdo antes
    msg_resched = BroadcastMessage(
        id="b-m-resched",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Bom dia",
        status=BroadcastStatus.MISFIRED,
        scheduled_at=now,
    )
    msg_resched.update_content("Boa tarde", None)
    msg_resched.reschedule(future)
    assert msg_resched.status is BroadcastStatus.SCHEDULED
    assert msg_resched.scheduled_at == future
    assert msg_resched.text == "Boa tarde"

    # De MISFIRED -> DISPATCHING via start_dispatch
    for dispatchable in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED, BroadcastStatus.MISFIRED):
        msg_disp = BroadcastMessage(
            id="b-m-disp",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Envio imediato",
            status=dispatchable,
            scheduled_at=now,
        )
        msg_disp.start_dispatch()
        assert msg_disp.status is BroadcastStatus.DISPATCHING

    # De MISFIRED -> CANCELLED via cancel
    msg_cancel = BroadcastMessage(
        id="b-m-cancel",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Descartar",
        status=BroadcastStatus.MISFIRED,
        scheduled_at=now,
    )
    msg_cancel.cancel()
    assert msg_cancel.status is BroadcastStatus.CANCELLED

    # Guardas de estados não permitidos para mark_misfired
    for invalid_misfire_status in (
        BroadcastStatus.MISFIRED,
        BroadcastStatus.DISPATCHING,
        BroadcastStatus.COMPLETED,
        BroadcastStatus.PARTIALLY_COMPLETED,
        BroadcastStatus.FAILED,
        BroadcastStatus.CANCELLED,
    ):
        invalid_msg = BroadcastMessage(
            id="b-inv-m",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Inv",
            status=invalid_misfire_status,
        )
        with pytest.raises(ValueError, match=r"^Only pending or scheduled broadcasts can become misfired$"):
            invalid_msg.mark_misfired()

    # Guardas de estados terminais/em voo para start_dispatch
    for invalid_dispatch_status in (
        BroadcastStatus.DISPATCHING,
        BroadcastStatus.COMPLETED,
        BroadcastStatus.PARTIALLY_COMPLETED,
        BroadcastStatus.FAILED,
        BroadcastStatus.CANCELLED,
    ):
        invalid_msg = BroadcastMessage(
            id="b-inv-d",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Inv",
            status=invalid_dispatch_status,
        )
        with pytest.raises(ValueError, match=r"^Cannot dispatch an in-flight, completed, failed, or cancelled broadcast$"):
            invalid_msg.start_dispatch()


def test_remove_and_replace_target_channel_on_broadcast_message():
    for active_status in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED, BroadcastStatus.MISFIRED):
        msg = BroadcastMessage(
            id="b-rem",
            profile_id="p-1",
            target_channel_ids=["-1001111111111", "-1002222222222"],
            text="Multi-channel",
            status=active_status,
        )
        assert msg.is_pending_or_scheduled() is True
        # Canal que não está na lista retorna False sem alterar nada
        assert msg.remove_target_channel("-1009999999999") is False
        assert msg.target_channel_ids == ["-1001111111111", "-1002222222222"]
        assert msg.status is active_status

        # Remover um canal quando há outro mantém o status e reduz a lista
        assert msg.remove_target_channel("-1001111111111") is True
        assert msg.target_channel_ids == ["-1002222222222"]
        assert msg.status is active_status

        # Remover o último canal cancela o agendamento
        assert msg.remove_target_channel("-1002222222222") is True
        assert msg.target_channel_ids == []
        assert msg.status is BroadcastStatus.CANCELLED
        assert msg.is_pending_or_scheduled() is False

    # Substituir canal preserva ordem e desduplica se o novo já estiver presente
    for active_status in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED, BroadcastStatus.MISFIRED):
        msg_rep = BroadcastMessage(
            id="b-rep",
            profile_id="p-1",
            target_channel_ids=["-1001111111111", "-1002222222222"],
            text="Replace test",
            status=active_status,
        )
        assert msg_rep.replace_target_channel("-1001111111111", "-1001111111111") is False
        assert msg_rep.replace_target_channel("-1009999999999", "-1003333333333") is False
        assert msg_rep.replace_target_channel("-1001111111111", "-1003333333333") is True
        assert msg_rep.target_channel_ids == ["-1003333333333", "-1002222222222"]
        # Se substituir pelo outro canal que já está na lista, não duplica
        assert msg_rep.replace_target_channel("-1003333333333", "-1002222222222") is True
        assert msg_rep.target_channel_ids == ["-1002222222222"]

    # Bloqueio em DISPATCHING
    msg_disp = BroadcastMessage(
        id="b-disp",
        profile_id="p-1",
        target_channel_ids=["-1001111111111"],
        status=BroadcastStatus.DISPATCHING,
    )
    assert msg_disp.is_pending_or_scheduled() is False
    with pytest.raises(
        ValueError,
        match=r"^There is a broadcast currently dispatching\. Wait for it to finish and try again\.$",
    ):
        msg_disp.remove_target_channel("-1001111111111")
    with pytest.raises(
        ValueError,
        match=r"^There is a broadcast currently dispatching\. Wait for it to finish and try again\.$",
    ):
        msg_disp.replace_target_channel("-1001111111111", "-1002222222222")

    # Bloqueio em estados terminais
    for terminal_status in (
        BroadcastStatus.COMPLETED,
        BroadcastStatus.PARTIALLY_COMPLETED,
        BroadcastStatus.FAILED,
        BroadcastStatus.CANCELLED,
    ):
        msg_term = BroadcastMessage(
            id="b-term",
            profile_id="p-1",
            target_channel_ids=["-1001111111111"],
            status=terminal_status,
        )
        assert msg_term.is_pending_or_scheduled() is False
        with pytest.raises(
            ValueError,
            match=r"^Cannot modify target channels of a completed, failed, or cancelled broadcast$",
        ):
            msg_term.remove_target_channel("-1001111111111")
        with pytest.raises(
            ValueError,
            match=r"^Cannot modify target channels of a completed, failed, or cancelled broadcast$",
        ):
            msg_term.replace_target_channel("-1001111111111", "-1002222222222")


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
