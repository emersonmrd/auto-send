from datetime import datetime, timezone
import logging
import os
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.domain.broadcast.broadcast_message import BroadcastStatus
from src.domain.ports.broadcast_repository import IBroadcastRepository
from src.domain.ports.profile_repository import IProfileRepository
from src.domain.ports.telegram_gateway import ITelegramGateway

logger = logging.getLogger(__name__)

class AutomationSchedulerService:
    def __init__(
        self,
        scheduler: Optional[AsyncIOScheduler] = None,
        broadcast_repo: Optional[IBroadcastRepository] = None,
        profile_repo: Optional[IProfileRepository] = None,
        telegram_gateway: Optional[ITelegramGateway] = None,
        reconcile_interval_seconds: int = 10,
    ):
        self.scheduler = scheduler or AsyncIOScheduler(
            timezone=timezone.utc,
            job_defaults={"misfire_grace_time": 3600, "coalesce": True},
        )
        self.broadcast_repo = broadcast_repo
        self.profile_repo = profile_repo
        self.telegram_gateway = telegram_gateway
        self.reconcile_interval_seconds = reconcile_interval_seconds
        self._executing_ids: set[str] = set()

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
        if self.broadcast_repo and self.profile_repo and self.telegram_gateway:
            self.scheduler.add_job(
                self.reconcile_due_broadcasts,
                trigger="interval",
                seconds=self.reconcile_interval_seconds,
                id="reconcile_due_broadcasts",
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
                misfire_grace_time=3600,
                coalesce=True,
            )

    def shutdown(self, wait: bool = False) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)

    def schedule_broadcast(self, broadcast_id: str, run_date: datetime) -> str:
        if run_date.tzinfo is None:
            run_date = run_date.replace(tzinfo=timezone.utc)
        else:
            run_date = run_date.astimezone(timezone.utc)
        job = self.scheduler.add_job(
            self.execute_scheduled_broadcast,
            trigger="date",
            run_date=run_date,
            args=[broadcast_id],
            id=f"broadcast_{broadcast_id}",
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )
        return str(job.id)

    def cancel_scheduled_broadcast(self, broadcast_id: str) -> None:
        """Remove o job no APScheduler e remove arquivo de mídia temporária se existir em disco."""
        job_id = f"broadcast_{broadcast_id}"
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass  # Ignora caso o job não exista ou já tenha sido removido

    def reschedule_broadcast(self, broadcast_id: str, new_run_date: datetime) -> None:
        """Reprograma o job no APScheduler com a nova data UTC."""
        self.schedule_broadcast(broadcast_id=broadcast_id, run_date=new_run_date)

    async def reconcile_due_broadcasts(self) -> None:
        """Varredura periódica (fallback/startup) para disparar agendamentos vencidos ou reagendar futuros."""
        if not self.broadcast_repo or not self.profile_repo or not self.telegram_gateway:
            return
        try:
            pending_list = await self.broadcast_repo.list_pending_scheduled()
            now_utc = datetime.now(timezone.utc)
            for b in pending_list:
                if not b.scheduled_at:
                    continue
                sched_utc = (
                    b.scheduled_at.replace(tzinfo=timezone.utc)
                    if b.scheduled_at.tzinfo is None
                    else b.scheduled_at.astimezone(timezone.utc)
                )
                if sched_utc <= now_utc:
                    await self.execute_scheduled_broadcast(b.id)
                else:
                    job_id = f"broadcast_{b.id}"
                    if self.scheduler.running and self.scheduler.get_job(job_id) is None:
                        self.schedule_broadcast(b.id, sched_utc)
        except Exception as e:
            logger.exception(f"Error during reconcile_due_broadcasts: {e}")

    async def execute_scheduled_broadcast(self, broadcast_id: str) -> None:
        if not self.broadcast_repo or not self.profile_repo or not self.telegram_gateway:
            logger.error("Dependencies not configured for broadcast execution")
            return

        if broadcast_id in self._executing_ids:
            return
        self._executing_ids.add(broadcast_id)

        try:
            broadcast = await self.broadcast_repo.get_by_id(broadcast_id)
            if not broadcast:
                logger.error(f"Scheduled broadcast {broadcast_id} not found")
                return

            if broadcast.status not in [BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED]:
                return

            profile = await self.profile_repo.get_by_id(broadcast.profile_id)
            if not profile:
                broadcast.status = BroadcastStatus.FAILED
                await self.broadcast_repo.save(broadcast)
                self._cleanup_media(broadcast)
                return

            broadcast.status = BroadcastStatus.DISPATCHING
            await self.broadcast_repo.save(broadcast)

            success_count = 0
            try:
                for chat_id in broadcast.target_channel_ids:
                    ok = await self.telegram_gateway.send_broadcast(
                        bot_token=profile.credentials.token,
                        chat_id=chat_id,
                        message=broadcast,
                    )
                    if ok:
                        success_count += 1

                broadcast.finish_dispatch(delivered=success_count, total=len(broadcast.target_channel_ids))
            except Exception as e:
                logger.exception(f"Error executing scheduled broadcast {broadcast_id}: {e}")
                broadcast.status = BroadcastStatus.FAILED
            finally:
                await self.broadcast_repo.save(broadcast)
                self._cleanup_media(broadcast)
        finally:
            self._executing_ids.discard(broadcast_id)

    def _cleanup_media(self, broadcast) -> None:
        """Invariante: nenhum arquivo órfão no disco após o disparo."""
        if broadcast.media:
            for path in [broadcast.media.file_path, broadcast.media.thumbnail_path]:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError as e:
                        logger.warning(f"Could not remove temp file {path}: {e}")
