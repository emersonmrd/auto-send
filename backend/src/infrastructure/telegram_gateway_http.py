import os
import json
import logging
from typing import Any, Callable, Dict, List, Optional
import httpx
from src.domain.channels.chat_discovery import DiscoveredChat, PublicChatIdentifier
from src.domain.ports.chat_discovery_gateway import ChatDiscoveryError, IChatDiscoveryGateway
from src.domain.ports.telegram_gateway import ITelegramGateway
from src.domain.broadcast.broadcast_message import BroadcastMessage, DispatchStrategy, MediaType
from src.infrastructure.progress_reader import ProgressFileReader
from src.infrastructure.resilience import CircuitBreaker, CircuitBreakerOpenException

logger = logging.getLogger(__name__)

PUBLIC_TELEGRAM_API_URL = "https://api.telegram.org"
PUBLIC_API_MAX_BYTES = 50 * 1024 * 1024
# Tipos de update que trazem o chat onde o bot está (canal, supergrupo ou grupo).
_CHAT_UPDATE_KINDS = ("my_chat_member", "channel_post", "edited_channel_post", "message", "edited_message")
_BOT_LEFT_STATUSES = ("left", "kicked")


class TelegramGatewayHttp(ITelegramGateway, IChatDiscoveryGateway):
    def __init__(
        self,
        base_url: Optional[str] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        resolved_url = base_url or os.getenv("TELEGRAM_API_BASE_URL", PUBLIC_TELEGRAM_API_URL)
        self.base_url = resolved_url.rstrip("/")
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.last_error: Optional[str] = None

    async def resolve_effective_base_url(self) -> str:
        """
        Se TELEGRAM_API_ID e TELEGRAM_API_HASH estiverem definidos e o servidor Local Bot API
        configurado em self.base_url (http://telegram-bot-api:8081 no Compose, http://127.0.0.1:<porta>
        no pacote portátil) estiver inacessível, faz fallback transparente para https://api.telegram.org.
        Se TELEGRAM_API_ID ou TELEGRAM_API_HASH estiverem vazios, o servidor local não roda: usa a API pública.
        """
        api_id = os.getenv("TELEGRAM_API_ID", "").strip()
        api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()

        if self.base_url != PUBLIC_TELEGRAM_API_URL:
            if not api_id or not api_hash:
                return PUBLIC_TELEGRAM_API_URL
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    await client.get(self.base_url)
                return self.base_url
            except Exception:
                logger.warning(
                    f"Local Telegram Bot API ({self.base_url}) indisponível. "
                    f"Usando fallback transparente para {PUBLIC_TELEGRAM_API_URL}."
                )
                return PUBLIC_TELEGRAM_API_URL

        return self.base_url

    async def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        """
        Interpreta status e payload do Telegram, atualizando o Circuit Breaker conforme o status.
        Trata 429 com retry_after (ou Retry-After header/parameters.retry_after), 413, 5xx e network/status errors.
        """
        if response.status_code == 429:
            retry_after = 30.0  # default
            desc = "Too Many Requests"
            try:
                data = response.json()
                if isinstance(data, dict):
                    desc = data.get("description", desc)
                    if "parameters" in data:
                        retry_after = float(data["parameters"].get("retry_after", 30.0))
            except Exception:
                pass

            if "retry-after" in response.headers:
                try:
                    retry_after = float(response.headers["retry-after"])
                except ValueError:
                    pass

            await self.circuit_breaker.record_failure(retry_after=retry_after)
            self.last_error = f"Telegram API error (429): {desc}"
            logger.warning(f"Telegram returned 429 Rate Limit. retry_after={retry_after}s")
            return {"ok": False, "error_code": 429, "description": desc}

        if response.status_code == 413:
            desc = "Request Entity Too Large"
            try:
                data = response.json()
                if isinstance(data, dict) and data.get("description"):
                    desc = data["description"]
            except Exception:
                pass
            self.last_error = f"Telegram API error (413): {desc}"
            logger.error(f"Telegram 413 Payload Too Large: {desc}")
            return {"ok": False, "error_code": 413, "description": desc}

        if response.status_code >= 500:
            await self.circuit_breaker.record_failure()
            desc = f"Server Error {response.status_code}"
            try:
                data = response.json()
                if isinstance(data, dict) and data.get("description"):
                    desc = data["description"]
            except Exception:
                pass
            self.last_error = f"Telegram API error ({response.status_code}): {desc}"
            logger.error(f"Telegram server error: HTTP {response.status_code} - {desc}")
            return {"ok": False, "error_code": response.status_code, "description": desc}

        # 2xx, 4xx (exceto 413/429/5xx)
        try:
            data = response.json()
        except Exception:
            data = {"ok": False, "description": "Invalid JSON response"}

        if response.is_success and data.get("ok"):
            self.last_error = None
            await self.circuit_breaker.record_success()
        else:
            desc = data.get("description", f"HTTP {response.status_code}")
            self.last_error = f"Telegram API error ({response.status_code}): {desc}"
            logger.warning(f"Telegram API error ({response.status_code}): {desc}")

        return data

    async def validate_bot_token(self, token: str) -> Dict[str, Any]:
        await self.circuit_breaker.can_execute()
        effective_url = await self.resolve_effective_base_url()
        url = f"{effective_url}/bot{token}/getMe"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                data = await self._handle_response(resp)
                if not data.get("ok"):
                    raise ValueError(f"Telegram Bot Token validation failed: {data.get('description', 'Unknown error')}")
                return data.get("result", {})
        except httpx.RequestError as exc:
            await self.circuit_breaker.record_failure()
            logger.error(f"Network error validating bot token: {exc}")
            raise

    def _enrich_large_file_error(self, message: BroadcastMessage, effective_url: str) -> None:
        if (
            message.media
            and message.media.file_size > PUBLIC_API_MAX_BYTES
            and effective_url == PUBLIC_TELEGRAM_API_URL
        ):
            hint = (
                "Arquivo excede o limite de 50MB da API pública do Telegram. "
                "Configure TELEGRAM_API_ID e TELEGRAM_API_HASH para usar o Local Bot API Server (até 2GB)."
            )
            if self.last_error:
                self.last_error = f"{self.last_error} — {hint}"
            else:
                self.last_error = hint

    async def send_broadcast(
        self,
        bot_token: str,
        chat_id: str,
        message: BroadcastMessage,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        self.last_error = None
        await self.circuit_breaker.can_execute()
        effective_url = await self.resolve_effective_base_url()
        strategy = message.get_dispatch_strategy()

        # Monta botão inline se presente
        reply_markup = None
        if message.button:
            reply_markup = {
                "inline_keyboard": [
                    [{"text": message.button.text, "url": message.button.url}]
                ]
            }

        timeout = httpx.Timeout(connect=30.0, read=600.0, write=600.0, pool=60.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if strategy == DispatchStrategy.TEXT_ONLY:
                    send_url = f"{effective_url}/bot{bot_token}/sendMessage"
                    payload = {
                        "chat_id": chat_id,
                        "text": message.text,
                        "parse_mode": "HTML"
                    }
                    if reply_markup:
                        payload["reply_markup"] = reply_markup
                    resp = await client.post(send_url, json=payload)
                    data = await self._handle_response(resp)
                    return bool(data.get("ok"))

                is_photo = bool(message.media and message.media.media_type == MediaType.PHOTO)
                media_endpoint = "sendPhoto" if is_photo else "sendVideo"
                media_field = "photo" if is_photo else "video"
                mime_type = "image/jpeg" if is_photo else "video/mp4"

                if strategy == DispatchStrategy.SINGLE_MEDIA_WITH_CAPTION:
                    send_url = f"{effective_url}/bot{bot_token}/{media_endpoint}"
                    data = {
                        "chat_id": chat_id,
                        "caption": message.text,
                        "parse_mode": "HTML"
                    }
                    if not is_photo:
                        data["supports_streaming"] = "true"
                        if message.media and message.media.duration and message.media.duration > 0:
                            data["duration"] = str(int(message.media.duration))
                        if message.media and message.media.width and message.media.width > 0:
                            data["width"] = str(int(message.media.width))
                        if message.media and message.media.height and message.media.height > 0:
                            data["height"] = str(int(message.media.height))
                        if message.media and message.media.thumbnail_path and os.path.exists(message.media.thumbnail_path):
                            data["thumbnail"] = "attach://thumbnail"
                            data["thumb"] = "attach://thumbnail"
                    if reply_markup:
                        data["reply_markup"] = json.dumps(reply_markup)

                    # Envio do arquivo
                    if message.media and os.path.exists(message.media.file_path):
                        media_f = ProgressFileReader(message.media.file_path, callback=progress_callback)
                        thumb_f = None
                        try:
                            files = {media_field: (os.path.basename(message.media.file_path), media_f, mime_type)}
                            if not is_photo and message.media.thumbnail_path and os.path.exists(message.media.thumbnail_path):
                                thumb_basename = os.path.basename(message.media.thumbnail_path)
                                thumb_f = open(message.media.thumbnail_path, "rb")
                                files["thumbnail"] = (thumb_basename, thumb_f, "image/jpeg")
                            resp = await client.post(send_url, data=data, files=files)
                            res_data = await self._handle_response(resp)
                            ok = bool(res_data.get("ok"))
                            if not ok:
                                self._enrich_large_file_error(message, effective_url)
                            return ok
                        finally:
                            media_f.close()
                            if thumb_f:
                                thumb_f.close()
                    self.last_error = "Arquivo de mídia não encontrado no servidor antes do envio."
                    return False

                elif strategy == DispatchStrategy.SPLIT_TEXT_THEN_MEDIA:
                    # 1. Envia o texto completo com o botão
                    text_url = f"{effective_url}/bot{bot_token}/sendMessage"
                    text_payload = {
                        "chat_id": chat_id,
                        "text": message.text,
                        "parse_mode": "HTML"
                    }
                    if reply_markup:
                        text_payload["reply_markup"] = reply_markup
                    resp1 = await client.post(text_url, json=text_payload)
                    data1 = await self._handle_response(resp1)
                    ok1 = bool(data1.get("ok"))

                    # Se a primeira chamada já falhou ou causou abertura do circuit breaker, não tenta a segunda
                    if not ok1:
                        return False

                    # 2. Envia a mídia (foto ou vídeo) logo em seguida
                    media_url = f"{effective_url}/bot{bot_token}/{media_endpoint}"
                    if message.media and os.path.exists(message.media.file_path):
                        media_data = {"chat_id": chat_id}
                        if reply_markup:
                            media_data["reply_markup"] = json.dumps(reply_markup)
                        if not is_photo:
                            media_data["supports_streaming"] = "true"
                            if message.media.duration and message.media.duration > 0:
                                media_data["duration"] = str(int(message.media.duration))
                            if message.media.width and message.media.width > 0:
                                media_data["width"] = str(int(message.media.width))
                            if message.media.height and message.media.height > 0:
                                media_data["height"] = str(int(message.media.height))
                            if message.media.thumbnail_path and os.path.exists(message.media.thumbnail_path):
                                media_data["thumbnail"] = "attach://thumbnail"
                                media_data["thumb"] = "attach://thumbnail"
                        media_f = ProgressFileReader(message.media.file_path, callback=progress_callback)
                        thumb_f = None
                        try:
                            files = {media_field: (os.path.basename(message.media.file_path), media_f, mime_type)}
                            if not is_photo and message.media.thumbnail_path and os.path.exists(message.media.thumbnail_path):
                                thumb_basename = os.path.basename(message.media.thumbnail_path)
                                thumb_f = open(message.media.thumbnail_path, "rb")
                                files["thumbnail"] = (thumb_basename, thumb_f, "image/jpeg")
                            resp2 = await client.post(media_url, data=media_data, files=files)
                            data2 = await self._handle_response(resp2)
                            ok2 = bool(data2.get("ok"))
                            if not ok2:
                                self._enrich_large_file_error(message, effective_url)
                            return ok1 and ok2
                        finally:
                            media_f.close()
                            if thumb_f:
                                thumb_f.close()
                    return ok1

            return False
        except httpx.RequestError as exc:
            await self.circuit_breaker.record_failure()
            self.last_error = f"Network error: {exc}"
            self._enrich_large_file_error(message, effective_url)
            logger.error(f"Network error in send_broadcast: {exc}")
            raise

    async def discover_chats(self, bot_token: str) -> List[DiscoveredChat]:
        # Sem offset nenhum update é confirmado, e sem allowed_updates a configuração do bot fica como está:
        # a descoberta só lê. Updates ficam no Telegram por 24 h, por isso a tela pede uma mensagem no canal.
        result = await self._call_chat_api(bot_token, "getUpdates", {"timeout": "0"})
        chats: Dict[int, DiscoveredChat] = {}
        for update in result if isinstance(result, list) else []:
            for kind in _CHAT_UPDATE_KINDS:
                payload = update.get(kind)
                if not isinstance(payload, dict):
                    continue
                raw_chat = payload.get("chat") or {}
                status = (payload.get("new_chat_member") or {}).get("status")
                if kind == "my_chat_member" and status in _BOT_LEFT_STATUSES:
                    chats.pop(raw_chat.get("id"), None)
                    continue
                discovered = self._to_discovered_chat(raw_chat)
                if discovered is not None:
                    chats[raw_chat["id"]] = discovered
        return list(chats.values())

    async def resolve_chat(self, bot_token: str, identifier: PublicChatIdentifier) -> DiscoveredChat:
        result = await self._call_chat_api(bot_token, "getChat", {"chat_id": identifier.as_chat_id()})
        discovered = self._to_discovered_chat(result if isinstance(result, dict) else {})
        if discovered is None:
            raise ChatDiscoveryError(f"{identifier.as_chat_id()} is not a channel or group")
        return discovered

    async def _call_chat_api(self, bot_token: str, method: str, params: Dict[str, str]) -> Any:
        await self.circuit_breaker.can_execute()
        effective_url = await self.resolve_effective_base_url()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{effective_url}/bot{bot_token}/{method}", params=params)
        except httpx.RequestError as exc:
            # A mensagem do httpx pode trazer a URL, que contém o token: só o tipo do erro sai daqui.
            await self.circuit_breaker.record_failure()
            logger.error("Network error calling Telegram %s: %s", method, type(exc).__name__)
            raise ChatDiscoveryError(f"Telegram unreachable ({type(exc).__name__})") from None
        data = await self._handle_response(resp)
        if not data.get("ok"):
            raise ChatDiscoveryError(self.last_error or f"Telegram API error: {data.get('description', 'Unknown error')}")
        return data.get("result")

    @staticmethod
    def _to_discovered_chat(raw_chat: Dict[str, Any]) -> Optional[DiscoveredChat]:
        try:
            return DiscoveredChat(
                chat_id=str(raw_chat.get("id", "")),
                title=raw_chat.get("title") or "",
                chat_type=raw_chat.get("type", ""),
                username=raw_chat.get("username"),
            )
        except ValueError:
            # Conversa privada ou dado incompleto: não é um chat que possa virar canal.
            return None
