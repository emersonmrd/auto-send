import pytest
from src.domain.channels.chat_discovery import DiscoveredChat, PublicChatIdentifier


@pytest.mark.parametrize(
    "raw",
    [
        "@meucanal",
        "meucanal",
        "  @meucanal  ",
        "t.me/meucanal",
        "https://t.me/meucanal",
        "http://t.me/meucanal/",
        "https://telegram.me/meucanal",
        "T.ME/meucanal",
    ],
)
def test_public_identifier_accepts_username_and_public_link(raw):
    identifier = PublicChatIdentifier.parse(raw)
    assert identifier.username == "meucanal"
    assert identifier.as_chat_id() == "@meucanal"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "@",
        "@abcd",  # 4 caracteres: o Telegram exige 5
        "@" + "a" * 33,  # 33 caracteres: o Telegram aceita até 32
        "@1canal",  # começa com dígito
        "@meu-canal",
        "@meu canal",
        "https://t.me/+AbCdEf123",  # convite privado não tem username
        "https://t.me/joinchat/AbCdEf123",
        "https://evil.example/meucanal",
        "https://t.me/meucanal/123",  # link de mensagem
        "-1001234567890",
    ],
)
def test_public_identifier_rejects_what_is_not_a_public_username(raw):
    with pytest.raises(ValueError, match=r"^Invalid public chat identifier \(use @username or t\.me/username\)$"):
        PublicChatIdentifier.parse(raw)


def test_public_identifier_accepts_limits_of_username_length():
    assert PublicChatIdentifier.parse("@" + "a" * 5).username == "aaaaa"
    assert PublicChatIdentifier.parse("@" + "a" * 32).username == "a" * 32
    assert PublicChatIdentifier.parse("@canal_123").username == "canal_123"


def test_public_identifier_validates_when_built_directly():
    with pytest.raises(ValueError, match=r"^Invalid public chat identifier \(use @username or t\.me/username\)$"):
        PublicChatIdentifier(username="x")


def test_discovered_channel_and_supergroup_can_be_registered():
    channel = DiscoveredChat(chat_id="-1001234567890", title="Canal de Novidades", chat_type="channel", username="canalnovidades")
    supergroup = DiscoveredChat(chat_id="-1009876543210", title="Grupo", chat_type="supergroup")

    assert channel.is_registrable is True
    assert supergroup.is_registrable is True
    assert supergroup.username is None


def test_basic_group_is_listed_but_cannot_be_registered():
    # Grupo comum tem id sem -100 e não passa no invariante de Channel.
    group = DiscoveredChat(chat_id="-123456789", title="Grupo antigo", chat_type="group")
    assert group.is_registrable is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chat_id": "", "title": "X", "chat_type": "channel"},
        {"chat_id": "abc", "title": "X", "chat_type": "channel"},
        {"chat_id": "123", "title": "X", "chat_type": "channel"},
        {"chat_id": "-1001234567890", "title": "X", "chat_type": "private"},
        {"chat_id": "-1001234567890", "title": "X", "chat_type": "bot"},
    ],
)
def test_discovered_chat_rejects_invalid_data(kwargs):
    with pytest.raises(ValueError, match=r"^Invalid discovered chat \(expected a channel or group with a negative numeric id\)$"):
        DiscoveredChat(**kwargs)


def test_discovered_chat_is_immutable():
    chat = DiscoveredChat(chat_id="-1001234567890", title="Canal", chat_type="channel")
    with pytest.raises(AttributeError):
        chat.title = "Outro"  # type: ignore[misc]


def test_trailing_newline_is_not_accepted():
    with pytest.raises(ValueError):
        PublicChatIdentifier(username="meucanal\n")
    with pytest.raises(ValueError):
        DiscoveredChat(chat_id="-1001234567890\n", title="X", chat_type="channel")
    assert DiscoveredChat(chat_id="-123", title="X", chat_type="group").is_registrable is False


def test_public_identifier_is_immutable():
    identifier = PublicChatIdentifier.parse("@meucanal")
    with pytest.raises(AttributeError):
        identifier.username = "outrocanal"  # type: ignore[misc]
