import httpx
import pytest
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastPoll,
    DeliveryFailureCategory,
    MediaAttachment,
    MediaType,
)
from src.infrastructure.telegram_gateway_http import TelegramGatewayHttp, translate_telegram_error_pt
from tests.unit.test_chat_discovery_gateway_http import TOKEN, use_transport

# #107 parte B: com a conferência ligada, o gateway lê as permissões do bot antes de enviar e não tenta
# mandar ao destino o conteúdo que ele não pode enviar.
CHAT_ID = "-1001234567890"
BOT_ID = 123456789
ONLY_TEXT = {"can_send_messages": True, "can_send_photos": False, "can_send_videos": False, "can_send_polls": False}
ALL = {"can_send_messages": True, "can_send_photos": True, "can_send_videos": True, "can_send_polls": True}
SEND_METHODS = ("sendMessage", "sendPhoto", "sendVideo", "sendPoll")


def telegram(member: dict | None, chat: dict | None):
    def handler(req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[1]
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": BOT_ID, "is_bot": True}})
        if method == "getChatMember" and member is not None:
            return httpx.Response(200, json={"ok": True, "result": {"user": {"id": BOT_ID}, **member}})
        if method == "getChat" and chat is not None:
            return httpx.Response(200, json={"ok": True, "result": {"id": int(CHAT_ID), "title": "Acme", **chat}})
        if method in SEND_METHODS:
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1, "chat": {"id": int(CHAT_ID)}}})
        return httpx.Response(400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})

    return handler


def text_message():
    return BroadcastMessage(id="b-1", profile_id="p-1", target_channel_ids=[CHAT_ID], text="Olá")


def photo_message(tmp_path, text="Legenda"):
    path = tmp_path / "foto.jpg"
    path.write_bytes(b"\xff\xd8\xff fake jpeg")
    media = MediaAttachment(file_path=str(path), media_type=MediaType.PHOTO, file_size=path.stat().st_size)
    return BroadcastMessage(id="b-2", profile_id="p-1", target_channel_ids=[CHAT_ID], text=text, media=media)


def poll_message():
    return BroadcastMessage(
        id="b-3", profile_id="p-1", target_channel_ids=[CHAT_ID],
        poll=BroadcastPoll(question="Qual tema?", options=["A", "B"]),
    )


def methods(requests):
    return [r.url.path.rsplit("/", 1)[1] for r in requests]


async def send(monkeypatch, member, chat, message, check=True):
    requests = use_transport(monkeypatch, telegram(member, chat))
    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org", check_send_permissions=check)
    ok = await gateway.send_broadcast(TOKEN, CHAT_ID, message)
    return ok, gateway, requests


async def test_check_is_off_by_default(monkeypatch):
    requests = use_transport(monkeypatch, telegram({"status": "member"}, {"type": "supergroup", "permissions": {}}))
    ok = await TelegramGatewayHttp(base_url="https://api.telegram.org").send_broadcast(TOKEN, CHAT_ID, text_message())
    assert ok is True
    assert methods(requests) == ["sendMessage"]


async def test_allowed_content_is_sent_after_reading_the_permissions(monkeypatch):
    ok, _, requests = await send(monkeypatch, {"status": "member"}, {"type": "supergroup", "permissions": ONLY_TEXT}, text_message())
    assert ok is True
    assert methods(requests) == ["getMe", "getChatMember", "getChat", "sendMessage"]


async def test_photo_to_a_group_that_forbids_photos_is_not_sent(monkeypatch, tmp_path):
    ok, gateway, requests = await send(
        monkeypatch, {"status": "member"}, {"type": "supergroup", "permissions": ONLY_TEXT}, photo_message(tmp_path)
    )

    assert ok is False
    assert not set(methods(requests)) & set(SEND_METHODS)
    assert gateway.last_failure_category is DeliveryFailureCategory.NO_POST_PERMISSION
    assert gateway.last_failure_detail == "Bot cannot send photos in this group"
    assert gateway.last_error == gateway.last_failure_detail


async def test_long_text_with_photo_needs_text_too(monkeypatch, tmp_path):
    no_text = {**ALL, "can_send_messages": False}
    ok, gateway, requests = await send(
        monkeypatch, {"status": "member"}, {"type": "supergroup", "permissions": no_text}, photo_message(tmp_path, "A" * 1025)
    )
    assert ok is False
    assert gateway.last_failure_detail == "Bot cannot send text messages in this group"
    assert not set(methods(requests)) & set(SEND_METHODS)


@pytest.mark.parametrize(
    "message_factory, permissions, detail",
    [
        (lambda tmp: text_message(), {**ALL, "can_send_messages": False}, "Bot cannot send text messages in this group"),
        (lambda tmp: poll_message(), ONLY_TEXT, "Bot cannot send polls in this group"),
    ],
    ids=["text", "poll"],
)
async def test_each_forbidden_content_has_its_own_reason(monkeypatch, tmp_path, message_factory, permissions, detail):
    ok, gateway, _ = await send(monkeypatch, {"status": "member"}, {"type": "supergroup", "permissions": permissions}, message_factory(tmp_path))
    assert ok is False
    assert gateway.last_failure_detail == detail


async def test_video_reason(monkeypatch, tmp_path):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake")
    media = MediaAttachment(file_path=str(path), media_type=MediaType.VIDEO, file_size=path.stat().st_size)
    message = BroadcastMessage(id="b-4", profile_id="p-1", target_channel_ids=[CHAT_ID], text="Vídeo", media=media)
    ok, gateway, _ = await send(monkeypatch, {"status": "member"}, {"type": "supergroup", "permissions": ONLY_TEXT}, message)
    assert ok is False
    assert gateway.last_failure_detail == "Bot cannot send videos in this group"


async def test_channel_without_post_permission_keeps_the_channel_reason(monkeypatch):
    ok, gateway, requests = await send(
        monkeypatch, {"status": "administrator", "can_post_messages": False}, {"type": "channel"}, text_message()
    )
    assert ok is False
    assert gateway.last_failure_category is DeliveryFailureCategory.NO_POST_PERMISSION
    assert gateway.last_failure_detail == "Bot is not administrator in the channel"
    assert "sendMessage" not in methods(requests)


@pytest.mark.parametrize(
    "member, chat",
    [(None, None), ({"status": "left"}, {"type": "supergroup"}), ({"status": "kicked"}, {"type": "channel"})],
    ids=["telegram-refuses-the-read", "left", "kicked"],
)
async def test_bot_outside_the_chat_still_tries_and_gets_the_telegram_reason(monkeypatch, member, chat):
    # Bot fora do chat: o envio segue e o erro do Telegram é classificado como sempre (BOT_NOT_IN_CHAT).
    ok, _, requests = await send(monkeypatch, member, chat, text_message())
    assert ok is True
    assert methods(requests)[-1] == "sendMessage"


async def test_telegram_unavailable_on_the_read_does_not_block_the_send(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[1]
        if method == "sendMessage":
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        return httpx.Response(502, json={"ok": False, "error_code": 502, "description": "Bad Gateway"})

    requests = use_transport(monkeypatch, handler)
    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org", check_send_permissions=True)
    assert await gateway.send_broadcast(TOKEN, CHAT_ID, text_message()) is True
    assert methods(requests) == ["getMe", "sendMessage"]


async def test_reused_file_id_is_checked_too(monkeypatch, tmp_path):
    requests = use_transport(monkeypatch, telegram({"status": "member"}, {"type": "supergroup", "permissions": ONLY_TEXT}))
    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org", check_send_permissions=True)
    ok = await gateway.send_broadcast(TOKEN, CHAT_ID, photo_message(tmp_path), file_id="AgACAgEAAx-fake")
    assert ok is False
    assert not set(methods(requests)) & set(SEND_METHODS)


@pytest.mark.parametrize(
    "detail, expected",
    [
        ("Bot cannot send text messages in this group", "O bot não pode enviar mensagens de texto neste grupo"),
        ("Bot cannot send photos in this group", "O bot não pode enviar fotos neste grupo"),
        ("Bot cannot send videos in this group", "O bot não pode enviar vídeos neste grupo"),
        ("Bot cannot send polls in this group", "O bot não pode enviar enquetes neste grupo"),
    ],
)
def test_each_reason_has_a_portuguese_translation(detail, expected):
    assert translate_telegram_error_pt(detail).startswith(expected)
