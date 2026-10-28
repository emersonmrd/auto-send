import os
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional
import httpx
from src.domain.channels.chat_discovery import ChatIdentifier, DiscoveredChat
from src.domain.ports.chat_discovery_gateway import (
    BotInUseError,
    BotNotChannelAdminError,
    ChatDiscoveryError,
    IChatDiscoveryGateway,
    TelegramUnavailableError,
    WebhookActiveError,
)
from src.domain.ports.telegram_gateway import ITelegramGateway
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    ChannelDeliveryResult,
    DeliveryFailureCategory,
    DispatchStrategy,
    MediaType,
    PollType,
)
from src.infrastructure.progress_reader import ProgressFileReader
from src.infrastructure.resilience import CircuitBreaker, CircuitBreakerOpenException

logger = logging.getLogger(__name__)

PUBLIC_TELEGRAM_API_URL = "https://api.telegram.org"
PUBLIC_API_MAX_BYTES = 50 * 1024 * 1024
# Tipos de update que trazem o chat onde o bot está (canal, supergrupo ou grupo).
_CHAT_UPDATE_KINDS = ("my_chat_member", "channel_post", "edited_channel_post", "message", "edited_message")
_BOT_LEFT_STATUSES = ("left", "kicked")
_BOT_TOKEN_IN_URL_RE = re.compile(r"/bot[^/\s\"']+")
_BARE_BOT_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{10,}\b")


def redact_bot_token(text: str, bot_token: Optional[str] = None) -> str:
    """Remove qualquer ocorrência do token de bot de mensagens de erro ou logs (§9)."""
    if not text:
        return ""
    sanitized = _BOT_TOKEN_IN_URL_RE.sub("/bot[REDACTED]", text)
    if bot_token and bot_token in sanitized:
        sanitized = sanitized.replace(bot_token, "[REDACTED]")
    sanitized = _BARE_BOT_TOKEN_RE.sub("[REDACTED]", sanitized)
    return sanitized


TELEGRAM_ERROR_TRANSLATIONS_PT: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"chat not found", re.I), "Canal ou grupo não encontrado. Verifique se o ID ou @username está correto e se o bot é membro."),
    (re.compile(r"group chat was upgraded to a supergroup", re.I), "O grupo foi promovido para supergrupo e o identificador mudou. Atualize o canal com o novo ID (-100...)."),
    (re.compile(r"not enough rights|have no rights|chat_write_forbidden|need administrator rights", re.I), "O bot não tem permissão para enviar mensagens neste canal. Adicione o bot como administrador com permissão de publicar."),
    (re.compile(r"bot was blocked by the user", re.I), "O bot foi bloqueado pelo usuário."),
    (re.compile(r"bot was kicked|bot is not a member", re.I), "O bot não é membro ou foi removido deste canal. Adicione-o novamente como administrador."),
    (re.compile(r"message is too long", re.I), "A mensagem excede o limite de caracteres permitido pelo Telegram (máximo 4.096 caracteres)."),
    (re.compile(r"message caption is too long", re.I), "A legenda da mídia excede o limite de 1.024 caracteres do Telegram."),
    (re.compile(r"message text is empty", re.I), "O texto da mensagem não pode estar vazio."),
    (re.compile(r"BUTTON_URL_INVALID", re.I), "A URL informada para o botão é inválida."),
    (re.compile(r"can'?t parse entities", re.I), "A formatação HTML ou Markdown contém erros ou tags não suportadas pelo Telegram."),
    (re.compile(r"wrong file identifier|failed to get HTTP URL content", re.I), "Não foi possível carregar ou processar o arquivo de mídia enviado."),
    (re.compile(r"user is deactivated", re.I), "O canal ou usuário de destino foi desativado pelo Telegram."),
    (re.compile(r"unauthorized", re.I), "Token do bot inválido, revogado ou expirado. Confira o token no @BotFather."),
    (re.compile(r"too many requests", re.I), "Limite de requisições do Telegram excedido. Aguarde alguns instantes antes de tentar novamente."),
]


def translate_telegram_error_pt(description: Optional[str]) -> Optional[str]:
    """Traduz descrições e erros comuns da API do Telegram para mensagens claras em português (Issue #57)."""
    if not description or not description.strip():
        return None
    for pattern, translation in TELEGRAM_ERROR_TRANSLATIONS_PT:
        if pattern.search(description):
            return translation
    return None


def classify_telegram_error(
    status_code: Optional[int],
    description: Optional[str],
    bot_token: Optional[str] = None,
) -> tuple[DeliveryFailureCategory, str]:
    """Converte resposta de erro do Telegram em categoria pura do domínio (ACL, §2)."""
    clean_desc = redact_bot_token((description or "").strip(), bot_token=bot_token)
    lower = clean_desc.lower()

    if status_code == 401 or "unauthorized" in lower:
        return DeliveryFailureCategory.INVALID_TOKEN, clean_desc or "Unauthorized"
    if status_code == 429 or "too many requests" in lower:
        return DeliveryFailureCategory.RATE_LIMITED, clean_desc or "Too Many Requests"
    if status_code is not None and status_code >= 500:
        return DeliveryFailureCategory.TELEGRAM_UNAVAILABLE, clean_desc or f"Server Error {status_code}"

    if any(
        marker in lower
        for marker in (
            "chat not found",
            "bot was kicked",
            "bot is not a member",
            "user is deactivated",
            "channel_private",
            "group chat was upgraded",
        )
    ):
        return DeliveryFailureCategory.BOT_NOT_IN_CHAT, clean_desc

    if any(
        marker in lower
        for marker in (
            "not enough rights",
            "need administrator rights",
            "chat_write_forbidden",
            "chat_admin_required",
            "have no rights to send",
        )
    ) or status_code == 403:
        return DeliveryFailureCategory.NO_POST_PERMISSION, clean_desc

    return DeliveryFailureCategory.OTHER, clean_desc or (f"HTTP {status_code}" if status_code else "Unknown error")


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
        self.last_failure_category: Optional[DeliveryFailureCategory] = None
        self.last_failure_detail: Optional[str] = None
        self.last_uploaded_file_id: Optional[str] = None

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

    def _record_telegram_failure(self, status_code: int, desc: str) -> None:
        cat, clean_desc = classify_telegram_error(status_code, desc)
        self.last_error = f"Telegram API error ({status_code}): {clean_desc}"
        self.last_failure_category = cat
        self.last_failure_detail = clean_desc

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
            self._record_telegram_failure(429, desc)
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
            self._record_telegram_failure(413, desc)
            logger.error(f"Telegram 413 Payload Too Large: {redact_bot_token(desc)}")
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
            self._record_telegram_failure(response.status_code, desc)
            logger.error(f"Telegram server error: HTTP {response.status_code} - {redact_bot_token(desc)}")
            return {"ok": False, "error_code": response.status_code, "description": desc}

        # 2xx, 4xx (exceto 413/429/5xx)
        try:
            data = response.json()
        except Exception:
            data = {"ok": False, "description": "Invalid JSON response"}

        if response.is_success and data.get("ok"):
            self.last_error = None
            self.last_failure_category = None
            self.last_failure_detail = None
            await self.circuit_breaker.record_success()
        else:
            desc = data.get("description", f"HTTP {response.status_code}")
            self._record_telegram_failure(response.status_code, desc)
            logger.warning(f"Telegram API error ({response.status_code}): {self.last_failure_detail}")

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
                    clean = redact_bot_token(str(data.get("description", "Unknown error")), bot_token=token)
                    raise ValueError(f"Telegram Bot Token validation failed: {clean}")
                return data.get("result", {})
        except httpx.RequestError as exc:
            await self.circuit_breaker.record_failure()
            logger.error("Network error validating bot token: %s", redact_bot_token(str(exc), bot_token=token))
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
            if self.last_failure_detail:
                self.last_failure_detail = f"{self.last_failure_detail} — {hint}"
            else:
                self.last_failure_detail = hint

    def _extract_and_store_file_id(self, res_data: dict, is_photo: bool) -> None:
        """Captura o file_id do arquivo no retorno de sucesso do Telegram para reuso sem re-upload."""
        result = res_data.get("result", {})
        if not isinstance(result, dict):
            return
        if is_photo:
            photos = result.get("photo", [])
            if isinstance(photos, list) and photos:
                last_photo = photos[-1]
                if isinstance(last_photo, dict) and "file_id" in last_photo:
                    self.last_uploaded_file_id = last_photo["file_id"]
        else:
            vid = result.get("video", {})
            if isinstance(vid, dict) and "file_id" in vid:
                self.last_uploaded_file_id = vid["file_id"]

    async def send_broadcast(
        self,
        bot_token: str,
        chat_id: str,
        message: BroadcastMessage,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        file_id: Optional[str] = None,
    ) -> bool:
        self.last_error = None
        self.last_failure_category = None
        self.last_failure_detail = None
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
                if strategy == DispatchStrategy.POLL:
                    send_url = f"{effective_url}/bot{bot_token}/sendPoll"
                    poll = message.poll
                    if not poll:
                        self.last_error = "Dados da enquete ausentes no broadcast."
                        self.last_failure_category = DeliveryFailureCategory.OTHER
                        self.last_failure_detail = self.last_error
                        return False
                    payload = {
                        "chat_id": chat_id,
                        "question": poll.question,
                        "options": poll.options,
                        "is_anonymous": poll.is_anonymous,
                        "allows_multiple_answers": poll.allows_multiple_answers,
                        "type": poll.poll_type.value,
                    }
                    if poll.is_closed:
                        payload["is_closed"] = True
                    if poll.poll_type == PollType.QUIZ:
                        payload["correct_option_id"] = poll.correct_option_id
                        if poll.explanation:
                            payload["explanation"] = poll.explanation
                    if reply_markup:
                        payload["reply_markup"] = reply_markup
                    resp = await client.post(send_url, json=payload)
                    data = await self._handle_response(resp)
                    return bool(data.get("ok"))

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
                    if not message.text:
                        data.pop("caption", None)
                        data.pop("parse_mode", None)
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

                    # Reutilização instantânea de file_id (sem re-upload de binário)
                    if file_id:
                        data.pop("thumbnail", None)
                        data.pop("thumb", None)
                        data[media_field] = file_id
                        resp = await client.post(send_url, data=data)
                        res_data = await self._handle_response(resp)
                        ok = bool(res_data.get("ok"))
                        if not ok:
                            self._enrich_large_file_error(message, effective_url)
                        return ok

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
                            if ok:
                                self._extract_and_store_file_id(res_data, is_photo)
                            else:
                                self._enrich_large_file_error(message, effective_url)
                            return ok
                        finally:
                            media_f.close()
                            if thumb_f:
                                thumb_f.close()
                    self.last_error = "Arquivo de mídia não encontrado no servidor antes do envio."
                    self.last_failure_category = DeliveryFailureCategory.OTHER
                    self.last_failure_detail = self.last_error
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
                    media_data = {"chat_id": chat_id}
                    if reply_markup:
                        media_data["reply_markup"] = json.dumps(reply_markup)
                    if not is_photo:
                        media_data["supports_streaming"] = "true"
                        if message.media and message.media.duration and message.media.duration > 0:
                            media_data["duration"] = str(int(message.media.duration))
                        if message.media and message.media.width and message.media.width > 0:
                            media_data["width"] = str(int(message.media.width))
                        if message.media and message.media.height and message.media.height > 0:
                            media_data["height"] = str(int(message.media.height))
                        if message.media and message.media.thumbnail_path and os.path.exists(message.media.thumbnail_path):
                            media_data["thumbnail"] = "attach://thumbnail"
                            media_data["thumb"] = "attach://thumbnail"

                    # Reutilização instantânea de file_id
                    if file_id:
                        media_data.pop("thumbnail", None)
                        media_data.pop("thumb", None)
                        media_data[media_field] = file_id
                        resp2 = await client.post(media_url, data=media_data)
                        data2 = await self._handle_response(resp2)
                        ok2 = bool(data2.get("ok"))
                        if not ok2:
                            self._enrich_large_file_error(message, effective_url)
                        return ok1 and ok2

                    if message.media and os.path.exists(message.media.file_path):
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
                            if ok2:
                                self._extract_and_store_file_id(data2, is_photo)
                            else:
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
            clean_exc = redact_bot_token(str(exc), bot_token=bot_token)
            self.last_error = f"Network error: {clean_exc}"
            self.last_failure_category = DeliveryFailureCategory.TELEGRAM_UNAVAILABLE
            self.last_failure_detail = f"Network error ({type(exc).__name__})"
            self._enrich_large_file_error(message, effective_url)
            logger.error("Network error in send_broadcast: %s", clean_exc)
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

    async def resolve_chat(self, bot_token: str, identifier: ChatIdentifier) -> DiscoveredChat:
        result = await self._call_chat_api(bot_token, "getChat", {"chat_id": identifier.as_chat_id()})
        discovered = self._to_discovered_chat(result if isinstance(result, dict) else {})
        if discovered is None:
            raise ChatDiscoveryError(f"{identifier.as_chat_id()} is not a channel or group")
        return discovered

    async def ensure_bot_can_post(self, bot_token: str, chat_id: str) -> None:
        me = await self._call_member_api(bot_token, "getMe", {})
        bot_id = me.get("id") if isinstance(me, dict) else None
        if not bot_id:
            raise TelegramUnavailableError("Could not reach Telegram, try again")
        member = await self._call_member_api(
            bot_token,
            "getChatMember",
            {"chat_id": chat_id, "user_id": str(bot_id)},
        )
        status = member.get("status") if isinstance(member, dict) else None
        if status == "creator":
            return
        if status == "administrator" and member.get("can_post_messages", True) is not False:
            return
        raise BotNotChannelAdminError("Bot is not administrator in the channel")

    async def _call_member_api(self, bot_token: str, method: str, params: Dict[str, str]) -> Any:
        try:
            await self.circuit_breaker.can_execute()
        except CircuitBreakerOpenException:
            raise TelegramUnavailableError("Could not reach Telegram, try again") from None
        effective_url = await self.resolve_effective_base_url()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{effective_url}/bot{bot_token}/{method}", params=params)
        except httpx.RequestError as exc:
            # A mensagem do httpx pode trazer a URL com o token: nunca vaza para logs nem exceções (§9).
            await self.circuit_breaker.record_failure()
            logger.error("Network error calling Telegram %s: %s", method, type(exc).__name__)
            raise TelegramUnavailableError("Could not reach Telegram, try again") from None
        data = await self._handle_response(resp)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise TelegramUnavailableError("Could not reach Telegram, try again")
        if resp.is_success and not data.get("ok"):
            raise TelegramUnavailableError("Could not reach Telegram, try again")
        if not data.get("ok"):
            raise BotNotChannelAdminError("Bot is not administrator in the channel")
        return data.get("result")

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
        if resp.status_code == 409:
            # 409 no getUpdates ocorre em dois casos distintos (#32):
            # 1) "terminated by other getUpdates request" -> outro programa lendo updates do mesmo bot;
            # 2) "can't use getUpdates method while webhook is active" -> webhook ativo.
            # Nenhum dos dois é falha de servidor do Telegram (não abre o circuit breaker).
            desc_409 = ""
            try:
                body_409 = resp.json()
                if isinstance(body_409, dict):
                    desc_409 = str(body_409.get("description") or "")
            except Exception:
                desc_409 = ""
            lower_409 = desc_409.lower()
            if "terminated by other getupdates" in lower_409 or "other getupdates request" in lower_409:
                raise BotInUseError("Bot is currently in use by another program")
            raise WebhookActiveError("Bot webhook is active: automatic discovery is unavailable")
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


async def dispatch_broadcast_to_channel(
    gateway: ITelegramGateway,
    bot_token: str,
    chat_id: str,
    message: BroadcastMessage,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    file_id: Optional[str] = None,
) -> ChannelDeliveryResult:
    """Despacha para um canal e retorna o resultado estruturado por canal sem vazar o token (§2, §9)."""
    send_kwargs: Dict[str, Any] = {}
    if progress_callback is not None:
        send_kwargs["progress_callback"] = progress_callback
    if file_id is not None:
        send_kwargs["file_id"] = file_id
    try:
        ok = await gateway.send_broadcast(
            bot_token=bot_token,
            chat_id=chat_id,
            message=message,
            **send_kwargs,
        )
    except CircuitBreakerOpenException as exc:
        return ChannelDeliveryResult.failure(
            chat_id,
            category=DeliveryFailureCategory.TELEGRAM_UNAVAILABLE,
            detail=redact_bot_token(str(exc), bot_token=bot_token),
        )
    except httpx.RequestError as exc:
        return ChannelDeliveryResult.failure(
            chat_id,
            category=DeliveryFailureCategory.TELEGRAM_UNAVAILABLE,
            detail=f"Network error ({type(exc).__name__})",
        )
    except Exception as exc:
        return ChannelDeliveryResult.failure(
            chat_id,
            category=DeliveryFailureCategory.OTHER,
            detail=redact_bot_token(str(exc), bot_token=bot_token),
        )

    if ok:
        return ChannelDeliveryResult.success(chat_id)

    raw_cat = getattr(gateway, "last_failure_category", None)
    raw_detail = getattr(gateway, "last_failure_detail", None)
    raw_error = getattr(gateway, "last_error", None)

    detail: Optional[str] = None
    if isinstance(raw_detail, str) and raw_detail:
        detail = redact_bot_token(raw_detail, bot_token=bot_token)
    elif isinstance(raw_error, str) and raw_error:
        detail = redact_bot_token(raw_error, bot_token=bot_token)

    if isinstance(raw_cat, DeliveryFailureCategory):
        category = raw_cat
    elif detail:
        category, _ = classify_telegram_error(None, detail, bot_token=bot_token)
    else:
        category = DeliveryFailureCategory.OTHER

    return ChannelDeliveryResult.failure(chat_id, category=category, detail=detail)
