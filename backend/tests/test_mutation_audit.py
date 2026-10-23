import pytest
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    DispatchStrategy,
    InlineButton,
    MediaAttachment,
    MediaType,
    BroadcastStatus,
)
from src.domain.channels.channel import Channel
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile

def test_mutation_broadcast_strategy_boundary_mutations():
    """Garante que mutações em <= 1024 (como < 1024, <= 1023, > 1024) são mortas."""
    media = MediaAttachment(file_path="/tmp/v.mp4", media_type=MediaType.VIDEO, file_size=100)
    
    # Exatamente 1024 caracteres DEVE ser SINGLE_MEDIA_WITH_CAPTION
    msg_1024 = BroadcastMessage(
        id="1", profile_id="p", target_channel_ids=["-1001234567890"],
        text="A" * 1024, media=media
    )
    assert msg_1024.get_dispatch_strategy() == DispatchStrategy.SINGLE_MEDIA_WITH_CAPTION
    
    # 1025 caracteres DEVE ser SPLIT_TEXT_THEN_MEDIA
    msg_1025 = BroadcastMessage(
        id="2", profile_id="p", target_channel_ids=["-1001234567890"],
        text="A" * 1025, media=media
    )
    assert msg_1025.get_dispatch_strategy() == DispatchStrategy.SPLIT_TEXT_THEN_MEDIA
    
    # Sem mídia DEVE ser TEXT_ONLY
    msg_no_media = BroadcastMessage(
        id="3", profile_id="p", target_channel_ids=["-1001234567890"],
        text="Hello"
    )
    assert msg_no_media.get_dispatch_strategy() == DispatchStrategy.TEXT_ONLY

def test_mutation_inline_button_url_and_ip_checks():
    """Garante que mutações em schemes e ranges de IP privado são mortas."""
    # Scheme deve ser estritamente https
    with pytest.raises(ValueError, match="Only https:// allowed"):
        InlineButton(text="t", url="http://valid.com")
    with pytest.raises(ValueError, match="Only https:// allowed"):
        InlineButton(text="t", url="ftp://valid.com")
    with pytest.raises(ValueError, match="Only https:// allowed"):
        InlineButton(text="t", url="https://")

    # Localhost e loopback
    for host in ["localhost", "127.0.0.1", "0.0.0.0"]:
        with pytest.raises(ValueError, match="Private network prohibited"):
            InlineButton(text="t", url=f"https://{host}/path")

    # IPs privados (10.x, 192.168.x, 172.16.x)
    for priv in ["10.0.0.1", "192.168.0.1", "172.16.0.1", "127.0.0.2"]:
        with pytest.raises(ValueError, match="Private IP prohibited"):
            InlineButton(text="t", url=f"https://{priv}/path")

    # Domínio público válido
    btn = InlineButton(text="Valid", url="https://example.com/promo")
    assert btn.text == "Valid"
    assert btn.url == "https://example.com/promo"

def test_mutation_channel_chat_id_regex():
    """Garante que mutações no regex de chat_id do canal são mortas."""
    # Válido: -100 seguido de 9 ou mais dígitos
    c = Channel(id="c", profile_id="p", title="T", chat_id="-1001234567890")
    assert c.chat_id == "-1001234567890"

    # Mutações inválidas
    invalid_chat_ids = [
        "1001234567890",   # sem sinal negativo
        "-101234567890",   # prefixo errado
        "-10012345678",    # apenas 8 dígitos após -100
        "-100abcdefghij",  # letras ao invés de números
        "",                # vazio
    ]
    for bad_id in invalid_chat_ids:
        with pytest.raises(ValueError, match="Invalid Telegram Channel Chat ID format"):
            Channel(id="c", profile_id="p", title="T", chat_id=bad_id)

def test_mutation_profile_bot_credentials_and_status():
    """Garante que mutações no token de bot e ativação de perfil são mortas."""
    # Token válido
    creds = BotCredentials(token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="bot")
    assert creds.token == "123456789:ABCdefGhIJKlmNoPQRstuVWXyz12345"
    assert creds.bot_username == "bot"

    # Mutações de token inválido
    invalid_tokens = [
        "12345",           # sem dois pontos
        ":ABCdefGh",       # sem bot_id numérico
        "abc:ABCdefGh",    # bot_id não numérico
        "12345:short",     # secret token muito curto (< 10 chars)
    ]
    for bad_token in invalid_tokens:
        with pytest.raises(ValueError, match="Invalid Telegram Bot Token format"):
            BotCredentials(token=bad_token, bot_username="bot")

    # Mutações nos métodos activate() e deactivate()
    profile = Profile(id="m1", name="Profile 1", credentials=creds)
    assert profile.is_active is True
    profile.deactivate()
    assert profile.is_active is False
    profile.activate()
    assert profile.is_active is True

def test_mutation_broadcast_cancel_reschedule_update():
    """Garante que mutações nas transições de status de broadcast_message são mortas."""
    from datetime import datetime, timezone
    now = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    future = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)

    # Cancel: PENDING e SCHEDULED permitidos
    for valid_status in [BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED]:
        msg = BroadcastMessage(id="b", profile_id="p", target_channel_ids=["-1001"], status=valid_status)
        msg.cancel()
        assert msg.status == BroadcastStatus.CANCELLED

    # Cancel: DISPATCHING e COMPLETED proibidos
    for invalid_status in [BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED]:
        msg = BroadcastMessage(id="b", profile_id="p", target_channel_ids=["-1001"], status=invalid_status)
        with pytest.raises(ValueError, match="Cannot cancel an in-flight or completed broadcast"):
            msg.cancel()
        assert msg.status == invalid_status

    # Reschedule: PENDING e SCHEDULED permitidos, status vira SCHEDULED
    for valid_status in [BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED]:
        msg = BroadcastMessage(id="b", profile_id="p", target_channel_ids=["-1001"], status=valid_status, scheduled_at=now)
        msg.reschedule(future)
        assert msg.scheduled_at == future
        assert msg.status == BroadcastStatus.SCHEDULED

    # Reschedule: DISPATCHING, COMPLETED e CANCELLED proibidos
    for invalid_status in [BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED, BroadcastStatus.CANCELLED]:
        msg = BroadcastMessage(id="b", profile_id="p", target_channel_ids=["-1001"], status=invalid_status, scheduled_at=now)
        with pytest.raises(ValueError, match="Cannot reschedule an in-flight, completed, or cancelled broadcast"):
            msg.reschedule(future)
        assert msg.scheduled_at == now
        assert msg.status == invalid_status

    # Update content: PENDING e SCHEDULED permitidos
    btn = InlineButton(text="Link", url="https://example.com")
    for valid_status in [BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED]:
        msg = BroadcastMessage(id="b", profile_id="p", target_channel_ids=["-1001"], status=valid_status, text="old")
        msg.update_content("new text", btn)
        assert msg.text == "new text"
        assert msg.button == btn

    # Update content: DISPATCHING, COMPLETED e CANCELLED proibidos
    for invalid_status in [BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED, BroadcastStatus.CANCELLED]:
        msg = BroadcastMessage(id="b", profile_id="p", target_channel_ids=["-1001"], status=invalid_status, text="old")
        with pytest.raises(ValueError, match="Cannot update content of an in-flight, completed, or cancelled broadcast"):
            msg.update_content("new text")
        assert msg.text == "old"


@pytest.mark.asyncio
async def test_mutation_video_streaming_and_photo_payload_audit(tmp_path, monkeypatch):
    """Auditoria de mutação: garante que video sempre envia supports_streaming=true e photo nunca envia."""
    import httpx
    from src.infrastructure.telegram_gateway_http import TelegramGatewayHttp

    # Arquivos fake
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"dummy_video_stream")
    pic = tmp_path / "p.jpg"
    pic.write_bytes(b"dummy_photo_data")

    recorded = []
    def mock_handler(request: httpx.Request):
        recorded.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    # 1. Vídeo Direto (SINGLE_MEDIA_WITH_CAPTION)
    msg_v1 = BroadcastMessage(
        id="v1", profile_id="p", target_channel_ids=["-1001234567890"],
        text="Caption curta",
        media=MediaAttachment(file_path=str(vid), media_type=MediaType.VIDEO, file_size=100)
    )
    await gateway.send_broadcast("tok", "-1001234567890", msg_v1)
    req_v1 = recorded[-1]
    assert "sendVideo" in str(req_v1.url)
    assert b'name="supports_streaming"\r\n\r\ntrue\r\n' in req_v1.read()
    assert b"video/mp4" in req_v1.read()

    # 2. Vídeo Split (SPLIT_TEXT_THEN_MEDIA)
    msg_v2 = BroadcastMessage(
        id="v2", profile_id="p", target_channel_ids=["-1001234567890"],
        text="V" * 1050,
        media=MediaAttachment(file_path=str(vid), media_type=MediaType.VIDEO, file_size=100)
    )
    await gateway.send_broadcast("tok", "-1001234567890", msg_v2)
    req_v2 = recorded[-1]
    assert "sendVideo" in str(req_v2.url)
    assert b'name="supports_streaming"\r\n\r\ntrue\r\n' in req_v2.read()
    assert b"video/mp4" in req_v2.read()

    # 3. Foto Direto (SINGLE_MEDIA_WITH_CAPTION)
    msg_p1 = BroadcastMessage(
        id="p1", profile_id="p", target_channel_ids=["-1001234567890"],
        text="Caption foto",
        media=MediaAttachment(file_path=str(pic), media_type=MediaType.PHOTO, file_size=100)
    )
    await gateway.send_broadcast("tok", "-1001234567890", msg_p1)
    req_p1 = recorded[-1]
    assert "sendPhoto" in str(req_p1.url)
    assert b"supports_streaming" not in req_p1.read()
    assert b"image/jpeg" in req_p1.read()

    # 4. Foto Split (SPLIT_TEXT_THEN_MEDIA)
    msg_p2 = BroadcastMessage(
        id="p2", profile_id="p", target_channel_ids=["-1001234567890"],
        text="P" * 1050,
        media=MediaAttachment(file_path=str(pic), media_type=MediaType.PHOTO, file_size=100)
    )
    await gateway.send_broadcast("tok", "-1001234567890", msg_p2)
    req_p2 = recorded[-1]
    assert "sendPhoto" in str(req_p2.url)
    assert b"supports_streaming" not in req_p2.read()
    assert b"image/jpeg" in req_p2.read()


@pytest.mark.asyncio
async def test_mutation_profile_deletion_cascades_channels_and_broadcasts():
    """Auditoria de mutação: garante que SqlAlchemyProfileRepository.delete expurga canais e broadcasts vinculados."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy import select
    from src.infrastructure.sqlite_repositories import (
        Base,
        SqlAlchemyProfileRepository,
        SqlAlchemyChannelRepository,
        SqlAlchemyBroadcastRepository,
        ChannelModel,
        BroadcastModel,
        ProfileModel,
    )

    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    profile_repo = SqlAlchemyProfileRepository(session_factory)
    channel_repo = SqlAlchemyChannelRepository(session_factory)
    broadcast_repo = SqlAlchemyBroadcastRepository(session_factory)

    profile = Profile(
        id="profile-mut-del",
        name="Mut Profile",
        credentials=BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="mut_bot"),
    )
    await profile_repo.save(profile)

    channel = Channel(id="c-mut-1", profile_id=profile.id, title="Chan", chat_id="-1001234567890")
    await channel_repo.save(channel)

    bcast = BroadcastMessage(id="b-mut-1", profile_id=profile.id, target_channel_ids=["-1001234567890"], text="Text")
    await broadcast_repo.save(bcast)

    # Executa deleção
    deleted = await profile_repo.delete(profile.id)
    assert deleted is True

    # Mutação em qualquer dos 3 deletes deixará registros órfãos
    async with session_factory() as session:
        rem_profiles = (await session.execute(select(ProfileModel).where(ProfileModel.id == profile.id))).scalars().all()
        rem_channels = (await session.execute(select(ChannelModel).where(ChannelModel.profile_id == profile.id))).scalars().all()
        rem_broadcasts = (await session.execute(select(BroadcastModel).where(BroadcastModel.profile_id == profile.id))).scalars().all()

        assert len(rem_profiles) == 0, "Mutante sobreviveu: ProfileModel não foi deletado"
        assert len(rem_channels) == 0, "Mutante sobreviveu: ChannelModel órfão deixado no banco"
        assert len(rem_broadcasts) == 0, "Mutante sobreviveu: BroadcastModel órfão deixado no banco"

    await test_engine.dispose()
