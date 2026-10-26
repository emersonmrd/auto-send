from datetime import datetime, timedelta, timezone
import logging
import os
from typing import Callable, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.domain.broadcast.broadcast_message import (
    BroadcastStatus,
    ChannelDeliveryResult,
    DEFAULT_MISFIRE_GRACE_MINUTES,
    DeliveryFailureCategory,
    DueScheduleAction,
    evaluate_due_schedule,
)
from src.domain.ports.broadcast_repository import IBroadcastRepository
from src.domain.ports.profile_repository import IProfileRepository
from src.domain.ports.telegram_gateway import ITelegramGateway
from src.infrastructure.telegram_gateway_http import dispatch_broadcast_to_channel, redact_bot_token

logger = logging.getLogger(__name__)


def _read_misfire_grace_minutes() -> int:
    raw = os.getenv("SCHEDULE_MISFIRE_GRACE_MINUTES", "").strip()
    if not raw:
        return DEFAULT_MISFIRE_GRACE_MINUTES
    try:
        parsed = int(raw)
        return parsed if parsed >= 0 else DEFAULT_MISFIRE_GRACE_MINUTES
    except ValueError:
        return DEFAULT_MISFIRE_GRACE_MINUTES


class AutomationSchedulerService:
    def __init__(
        self,
        scheduler: Optional[AsyncIOScheduler] = None,
        broadcast_repo: Optional[IBroadcastRepository] = None,
        profile_repo: Optional[IProfileRepository] = None,
        telegram_gateway: Optional[ITelegramGateway] = None,
        reconcile_interval_seconds: int = 10,
        misfire_grace_minutes: Optional[int] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        # misfire_grace_time=None: o APScheduler nunca descarta em silêncio um job atrasado (ex.: suspensão do PC);
        # quem decide se dispara ou vira MISFIRED é a regra pura do domínio (evaluate_due_schedule, #1).
        self.scheduler = scheduler or AsyncIOScheduler(
            timezone=timezone.utc,
            job_defaults={"misfire_grace_time": None, "coalesce": True},
        )
        self.broadcast_repo = broadcast_repo
        self.profile_repo = profile_repo
        self.telegram_gateway = telegram_gateway
        self.reconcile_interval_seconds = reconcile_interval_seconds
        self._explicit_grace_minutes = misfire_grace_minutes
        self._clock = clock
        self._executing_ids: set[str] = set()

    @property
    def misfire_grace_window(self) -> timedelta:
        minutes = (
            self._explicit_grace_minutes
            if self._explicit_grace_minutes is not None
            else _read_misfire_grace_minutes()
        )
        return timedelta(minutes=minutes)

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
                next_run_time=self._clock(),
                misfire_grace_time=None,
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
            misfire_grace_time=None,
            coalesce=True,
        )
        return str(job.id)

    def cancel_scheduled_broadcast(self, broadcast_id: str) -> None:
        """Remove o job no APScheduler."""
        job_id = f"broadcast_{broadcast_id}"
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass  # Ignora caso o job não exista ou já tenha sido removido

    def reschedule_broadcast(self, broadcast_id: str, new_run_date: datetime) -> None:
        """Reprograma o job no APScheduler com a nova data UTC."""
        self.schedule_broadcast(broadcast_id=broadcast_id, run_date=new_run_date)

    async def reconcile_due_broadcasts(self) -> None:
        """Varredura periódica (fallback/startup) para disparar agendamentos na janela, marcar MISFIRED ou agendar futuros."""
        if not self.broadcast_repo or not self.profile_repo or not self.telegram_gateway:
            return
        try:
            pending_list = await self.broadcast_repo.list_pending_scheduled()
            now_utc = self._clock()
            grace_window = self.misfire_grace_window
            for b in pending_list:
                if not b.scheduled_at:
                    continue
                if b.is_edit_locked(now_utc):
                    if b.edit_locked_until and self.scheduler.running:
                        self.schedule_broadcast(b.id, b.edit_locked_until)
                    continue
                if b.expire_overdue_edit_lock(now_utc):
                    self.cancel_scheduled_broadcast(b.id)
                    await self.broadcast_repo.save(b)
                    self._cleanup_media(b)
                    continue
                sched_utc = (
                    b.scheduled_at.replace(tzinfo=timezone.utc)
                    if b.scheduled_at.tzinfo is None
                    else b.scheduled_at.astimezone(timezone.utc)
                )
                decision = evaluate_due_schedule(sched_utc, now_utc, grace_window)
                if decision is DueScheduleAction.WAIT:
                    job_id = f"broadcast_{b.id}"
                    if self.scheduler.running and self.scheduler.get_job(job_id) is None:
                        self.schedule_broadcast(b.id, sched_utc)
                elif decision is DueScheduleAction.MISFIRE:
                    b.mark_misfired()
                    self.cancel_scheduled_broadcast(b.id)
                    await self.broadcast_repo.save(b)
                else:
                    await self.execute_scheduled_broadcast(b.id)
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

            now_utc = self._clock()
            if broadcast.is_edit_locked(now_utc):
                if broadcast.edit_locked_until and self.scheduler.running:
                    self.schedule_broadcast(broadcast.id, broadcast.edit_locked_until)
                return

            if broadcast.expire_overdue_edit_lock(now_utc):
                self.cancel_scheduled_broadcast(broadcast.id)
                await self.broadcast_repo.save(broadcast)
                self._cleanup_media(broadcast)
                return

            # Mesma regra quando o job do APScheduler dispara atrasado (ex.: suspensão do PC, #1).
            if broadcast.scheduled_at is not None:
                sched_utc = (
                    broadcast.scheduled_at.replace(tzinfo=timezone.utc)
                    if broadcast.scheduled_at.tzinfo is None
                    else broadcast.scheduled_at.astimezone(timezone.utc)
                )
                decision = evaluate_due_schedule(
                    sched_utc,
                    self._clock(),
                    self.misfire_grace_window,
                )
                if decision is DueScheduleAction.MISFIRE:
                    broadcast.mark_misfired()
                    self.cancel_scheduled_broadcast(broadcast.id)
                    await self.broadcast_repo.save(broadcast)
                    return
                if decision is DueScheduleAction.WAIT:
                    # Job adiantado (ex.: reagendado para o fim de uma trava de edição, #15): volta para o horário.
                    if self.scheduler.running:
                        self.schedule_broadcast(broadcast.id, sched_utc)
                    return

            profile = await self.profile_repo.get_by_id(broadcast.profile_id)
            if not profile:
                broadcast.fail_all_channels(
                    DeliveryFailureCategory.OTHER,
                    detail="Profile not found",
                )
                await self.broadcast_repo.save(broadcast)
                self._cleanup_media(broadcast)
                return

            broadcast.start_dispatch()
            await self.broadcast_repo.save(broadcast)

            results: list[ChannelDeliveryResult] = []
            try:
                for chat_id in broadcast.target_channel_ids:
                    res = await dispatch_broadcast_to_channel(
                        gateway=self.telegram_gateway,
                        bot_token=profile.credentials.token,
                        chat_id=chat_id,
                        message=broadcast,
                    )
                    results.append(res)

                broadcast.finish_dispatch_with_results(results)
            except Exception as e:
                clean_err = redact_bot_token(str(e), bot_token=profile.credentials.token)
                logger.exception(f"Error executing scheduled broadcast {broadcast_id}: {clean_err}")
                broadcast.fail_all_channels(
                    DeliveryFailureCategory.OTHER,
                    detail=clean_err,
                )
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
