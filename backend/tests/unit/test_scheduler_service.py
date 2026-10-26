from datetime import datetime, timezone
import os
import pytest
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastStatus,
    MediaAttachment,
    MediaType,
)
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.infrastructure.in_memory_broadcast_repository import InMemoryBroadcastRepository
from src.infrastructure.in_memory_repositories import InMemoryProfileRepository
from src.infrastructure.scheduler_service import AutomationSchedulerService

class MockTelegramGateway:
    def __init__(self, should_succeed: bool = True):
        self.should_succeed = should_succeed
        self.sent_calls = []

    async def validate_bot_token(self, token: str):
        return {"id": 1, "username": "test_bot"}

    async def send_broadcast(self, bot_token: str, chat_id: str, message: BroadcastMessage):
        self.sent_calls.append((bot_token, chat_id, message.id))
        return self.should_succeed

@pytest.mark.asyncio
async def test_scheduler_service_executes_and_deletes_temp_media():
    temp_file = "/tmp/test_scheduled_media.mp4"
    with open(temp_file, "wb") as f:
        f.write(b"dummy video data")
    assert os.path.exists(temp_file)

    broadcast_repo = InMemoryBroadcastRepository()
    profile_repo = InMemoryProfileRepository()
    gateway = MockTelegramGateway(should_succeed=True)
    service = AutomationSchedulerService(
        broadcast_repo=broadcast_repo,
        profile_repo=profile_repo,
        telegram_gateway=gateway,
    )

    creds = BotCredentials(token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz", bot_username="bot")
    profile = Profile(id="p-1", name="Profile 1", credentials=creds)
    await profile_repo.save(profile)

    media = MediaAttachment(file_path=temp_file, media_type=MediaType.VIDEO, file_size=16)
    broadcast = BroadcastMessage(
        id="b-sched-1",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Scheduled post",
        media=media,
        scheduled_at=datetime.now(timezone.utc),
    )
    await broadcast_repo.save(broadcast)

    await service.execute_scheduled_broadcast(broadcast.id)

    updated = await broadcast_repo.get_by_id(broadcast.id)
    assert updated.status == BroadcastStatus.COMPLETED
    assert len(gateway.sent_calls) == 1
    # Garante que o arquivo temporário foi excluído
    assert not os.path.exists(temp_file)

@pytest.mark.asyncio
async def test_scheduler_handles_missing_profile_and_cleans_media():
    temp_file = "/tmp/test_scheduled_orphan.mp4"
    with open(temp_file, "wb") as f:
        f.write(b"data")

    broadcast_repo = InMemoryBroadcastRepository()
    profile_repo = InMemoryProfileRepository()
    gateway = MockTelegramGateway()
    service = AutomationSchedulerService(
        broadcast_repo=broadcast_repo,
        profile_repo=profile_repo,
        telegram_gateway=gateway,
    )

    media = MediaAttachment(file_path=temp_file, media_type=MediaType.VIDEO, file_size=4)
    broadcast = BroadcastMessage(
        id="b-sched-2",
        profile_id="non-existent-profile",
        target_channel_ids=["-1001234567890"],
        text="Scheduled post",
        media=media,
    )
    await broadcast_repo.save(broadcast)

    await service.execute_scheduled_broadcast(broadcast.id)

    updated = await broadcast_repo.get_by_id(broadcast.id)
    assert updated.status == BroadcastStatus.FAILED
    assert len(updated.delivery_results) == 1
    assert updated.delivery_results[0].delivered is False
    assert updated.delivery_results[0].detail == "Profile not found"
    assert not os.path.exists(temp_file)

@pytest.mark.asyncio
async def test_scheduler_cancel_and_reschedule():
    service = AutomationSchedulerService()
    service.start()
    try:
        run_dt = datetime.now(timezone.utc)
        job_id = service.schedule_broadcast("b-123", run_dt)
        assert job_id == "broadcast_b-123"
        assert service.scheduler.get_job("broadcast_b-123") is not None

        # Reschedule
        new_dt = datetime.now(timezone.utc)
        service.reschedule_broadcast("b-123", new_dt)
        assert service.scheduler.get_job("broadcast_b-123") is not None

        # Cancel
        service.cancel_scheduled_broadcast("b-123")
        assert service.scheduler.get_job("broadcast_b-123") is None

        # Cancel de job inexistente não levanta exceção
        service.cancel_scheduled_broadcast("non-existent")
    finally:
        service.shutdown(wait=False)


@pytest.mark.asyncio
async def test_scheduler_real_time_execution_after_delay():
    """
    Agenda um broadcast real para daqui a 1 segundo com o AsyncIOScheduler ligado,
    aguarda asyncio.sleep(2.5) sem chamar execute_scheduled_broadcast manualmente,
    e comprova que o status muda de SCHEDULED para COMPLETED automaticamente.
    """
    import asyncio
    from datetime import timedelta

    broadcast_repo = InMemoryBroadcastRepository()
    profile_repo = InMemoryProfileRepository()
    gateway = MockTelegramGateway(should_succeed=True)
    service = AutomationSchedulerService(
        broadcast_repo=broadcast_repo,
        profile_repo=profile_repo,
        telegram_gateway=gateway,
        reconcile_interval_seconds=2,
    )
    service.start()
    try:
        creds = BotCredentials(token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz", bot_username="bot")
        profile = Profile(id="m-realtime", name="Profile Realtime", credentials=creds)
        await profile_repo.save(profile)

        run_at = datetime.now(timezone.utc) + timedelta(seconds=1)
        broadcast = BroadcastMessage(
            id="b-realtime-1",
            profile_id="m-realtime",
            target_channel_ids=["-1001234567890"],
            text="Automated timer test",
            status=BroadcastStatus.SCHEDULED,
            scheduled_at=run_at,
        )
        await broadcast_repo.save(broadcast)
        service.schedule_broadcast(broadcast.id, run_at)

        # Aguarda até 5 segundos de forma resiliente para execução assíncrona do APScheduler
        for _ in range(25):
            updated = await broadcast_repo.get_by_id(broadcast.id)
            if updated and updated.status == BroadcastStatus.COMPLETED:
                break
            await asyncio.sleep(0.2)

        updated = await broadcast_repo.get_by_id(broadcast.id)
        assert updated is not None
        assert updated.status == BroadcastStatus.COMPLETED
        assert len(gateway.sent_calls) == 1
    finally:
        service.shutdown(wait=False)


@pytest.mark.asyncio
async def test_scheduler_reconcile_due_broadcasts_fallback():
    """
    Garante que broadcasts SCHEDULED com scheduled_at <= now no banco
    (ex: após restart do servidor ou misfire) são disparados pelo reconcile_due_broadcasts.
    """
    from datetime import timedelta

    broadcast_repo = InMemoryBroadcastRepository()
    profile_repo = InMemoryProfileRepository()
    gateway = MockTelegramGateway(should_succeed=True)
    service = AutomationSchedulerService(
        broadcast_repo=broadcast_repo,
        profile_repo=profile_repo,
        telegram_gateway=gateway,
    )

    creds = BotCredentials(token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz", bot_username="bot")
    profile = Profile(id="m-reconcile", name="Profile Reconcile", credentials=creds)
    await profile_repo.save(profile)

    past_dt = datetime.now(timezone.utc) - timedelta(seconds=30)
    broadcast = BroadcastMessage(
        id="b-due-1",
        profile_id="m-reconcile",
        target_channel_ids=["-1001234567890"],
        text="Missed broadcast recovered by reconciliation",
        status=BroadcastStatus.SCHEDULED,
        scheduled_at=past_dt,
    )
    await broadcast_repo.save(broadcast)

    await service.reconcile_due_broadcasts()

    updated = await broadcast_repo.get_by_id("b-due-1")
    assert updated is not None
    assert updated.status == BroadcastStatus.COMPLETED
    assert len(gateway.sent_calls) == 1




class PartialTelegramGateway(MockTelegramGateway):
    """Entrega só no primeiro canal."""

    async def send_broadcast(self, bot_token: str, chat_id: str, message: BroadcastMessage):
        self.sent_calls.append((bot_token, chat_id, message.id))
        return chat_id == message.target_channel_ids[0]


@pytest.mark.asyncio
async def test_scheduled_partial_dispatch_is_recorded_as_partially_completed():
    broadcast_repo = InMemoryBroadcastRepository()
    profile_repo = InMemoryProfileRepository()
    service = AutomationSchedulerService(
        broadcast_repo=broadcast_repo, profile_repo=profile_repo, telegram_gateway=PartialTelegramGateway()
    )
    creds = BotCredentials(token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz", bot_username="bot")
    await profile_repo.save(Profile(id="p-1", name="Profile 1", credentials=creds))
    await broadcast_repo.save(
        BroadcastMessage(
            id="b-partial",
            profile_id="p-1",
            target_channel_ids=["-1001111111111", "-1002222222222"],
            text="Metade chega",
            scheduled_at=datetime.now(timezone.utc),
        )
    )

    await service.execute_scheduled_broadcast("b-partial")

    saved = await broadcast_repo.get_by_id("b-partial")
    assert saved.status == BroadcastStatus.PARTIALLY_COMPLETED
    assert [(r.chat_id, r.delivered) for r in saved.delivery_results] == [
        ("-1001111111111", True),
        ("-1002222222222", False),
    ]


@pytest.mark.asyncio
async def test_reconcile_marks_overdue_broadcast_beyond_grace_window_as_misfired_and_keeps_media(tmp_path):
    """
    Regressão #1: broadcast vencido há mais tempo que SCHEDULE_MISFIRE_GRACE_MINUTES
    NÃO é enviado e fica MISFIRED, preservando a mídia temporária até decisão do usuário.
    """
    from datetime import timedelta

    fixed_now = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)
    media_file = tmp_path / "promo_video.mp4"
    media_file.write_bytes(b"video-content")

    broadcast_repo = InMemoryBroadcastRepository()
    profile_repo = InMemoryProfileRepository()
    gateway = MockTelegramGateway(should_succeed=True)
    service = AutomationSchedulerService(
        broadcast_repo=broadcast_repo,
        profile_repo=profile_repo,
        telegram_gateway=gateway,
        misfire_grace_minutes=30,
        clock=lambda: fixed_now,
    )

    creds = BotCredentials(token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz", bot_username="bot")
    await profile_repo.save(Profile(id="p-misfire", name="Profile Misfire", credentials=creds))

    # Vencido há 2 horas (> 30 min) -> deve virar MISFIRED sem enviar
    overdue_broadcast = BroadcastMessage(
        id="b-overdue",
        profile_id="p-misfire",
        target_channel_ids=["-1001234567890"],
        text="Bom dia! Promoção das 8h",
        media=MediaAttachment(file_path=str(media_file), media_type=MediaType.VIDEO, file_size=13),
        status=BroadcastStatus.SCHEDULED,
        scheduled_at=fixed_now - timedelta(hours=2),
    )
    # Vencido há 20 minutos (<= 30 min) -> deve disparar normalmente
    within_grace_broadcast = BroadcastMessage(
        id="b-within-grace",
        profile_id="p-misfire",
        target_channel_ids=["-1001234567890"],
        text="Dentro da janela de 30 min",
        status=BroadcastStatus.SCHEDULED,
        scheduled_at=fixed_now - timedelta(minutes=20),
    )
    await broadcast_repo.save(overdue_broadcast)
    await broadcast_repo.save(within_grace_broadcast)

    await service.reconcile_due_broadcasts()

    updated_overdue = await broadcast_repo.get_by_id("b-overdue")
    assert updated_overdue is not None
    assert updated_overdue.status == BroadcastStatus.MISFIRED
    assert media_file.exists(), "A mídia deve ser mantida enquanto o agendamento estiver MISFIRED"

    updated_within = await broadcast_repo.get_by_id("b-within-grace")
    assert updated_within is not None
    assert updated_within.status == BroadcastStatus.COMPLETED
    assert [call[2] for call in gateway.sent_calls] == ["b-within-grace"]


@pytest.mark.asyncio
async def test_execute_scheduled_broadcast_after_pc_sleep_marks_misfired_instead_of_sending(tmp_path):
    """
    Mesma regra com o app aberto (#1 decisão 4): se o job do APScheduler atrasar além
    da janela (ex: suspensão do PC), execute_scheduled_broadcast marca como MISFIRED sem enviar.
    """
    from datetime import timedelta

    fixed_now = datetime(2026, 10, 24, 18, 0, 0, tzinfo=timezone.utc)
    media_file = tmp_path / "delayed.mp4"
    media_file.write_bytes(b"delayed-video")

    broadcast_repo = InMemoryBroadcastRepository()
    profile_repo = InMemoryProfileRepository()
    gateway = MockTelegramGateway(should_succeed=True)
    service = AutomationSchedulerService(
        broadcast_repo=broadcast_repo,
        profile_repo=profile_repo,
        telegram_gateway=gateway,
        misfire_grace_minutes=30,
        clock=lambda: fixed_now,
    )

    creds = BotCredentials(token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz", bot_username="bot")
    await profile_repo.save(Profile(id="p-sleep", name="Profile Sleep", credentials=creds))

    delayed_broadcast = BroadcastMessage(
        id="b-sleep",
        profile_id="p-sleep",
        target_channel_ids=["-1001234567890"],
        text="Atrasou por suspensão do PC",
        media=MediaAttachment(file_path=str(media_file), media_type=MediaType.VIDEO, file_size=13),
        status=BroadcastStatus.SCHEDULED,
        scheduled_at=fixed_now - timedelta(minutes=31),
    )
    await broadcast_repo.save(delayed_broadcast)

    await service.execute_scheduled_broadcast("b-sleep")

    updated = await broadcast_repo.get_by_id("b-sleep")
    assert updated is not None
    assert updated.status == BroadcastStatus.MISFIRED
    assert gateway.sent_calls == []
    assert media_file.exists()
