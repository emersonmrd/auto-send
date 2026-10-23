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

    assert (await broadcast_repo.get_by_id("b-partial")).status == BroadcastStatus.PARTIALLY_COMPLETED
