from datetime import datetime, timezone
from typing import List, Optional

from src.application.errors import InvalidScheduleFormatError
from src.domain.broadcast.broadcast_message import BroadcastPoll, ensure_schedulable
from src.domain.channels.channel import ChatType
from src.domain.ports.channel_repository import IChannelRepository


def parse_schedule(raw: str) -> datetime:
    """scheduled_at da API em UTC; data sem fuso é UTC e data no passado é recusada (AGENTS.md §12)."""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidScheduleFormatError() from None
    parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    ensure_schedulable(parsed, now=datetime.now(timezone.utc))
    return parsed


async def ensure_poll_fits_targets(
    poll: Optional[BroadcastPoll],
    profile_id: str,
    target_chat_ids: List[str],
    channel_repo: IChannelRepository,
) -> None:
    # Só os canais do próprio perfil contam; chat sem tipo conhecido conta como canal (#99).
    if poll is None:
        return
    kinds = {c.chat_id: c.chat_type for c in await channel_repo.list_by_profile(profile_id)}
    only_groups = all(kinds.get(chat_id) is ChatType.SUPERGROUP for chat_id in target_chat_ids)
    poll.ensure_fits_destinations(only_groups=only_groups)
