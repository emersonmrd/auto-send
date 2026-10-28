from src.domain.channels.channel import Channel
from src.domain.channels.chat_discovery import ChatIdentifier
from src.domain.ports.chat_discovery_gateway import ChatDiscoveryError, IChatDiscoveryGateway


async def classify_from_telegram(channel: Channel, bot_token: str, gateway: IChatDiscoveryGateway) -> None:
    """Grava no canal o tipo e o fórum que o getChat informa (#99).

    Só roda depois de o bot poder postar no chat; se o getChat falhar, o canal continua sem tipo
    (sem badge) em vez de bloquear o vínculo.
    """
    try:
        chat = await gateway.resolve_chat(bot_token, ChatIdentifier(channel.chat_id))
        channel.classify(chat.kind, chat.is_forum)
    except (ChatDiscoveryError, ValueError):
        return
