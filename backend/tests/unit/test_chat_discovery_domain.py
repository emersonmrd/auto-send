import dataclasses

import pytest
from src.domain.channels.channel import ChatType
from src.domain.channels.chat_discovery import DiscoveredChat, ChatIdentifier

INVALID = r"^Invalid chat identifier \(use @username, t\.me/username, a post link t\.me/c/\.\.\. or the -100\.\.\. chat ID\)$"
INVITE = r"^Invite links \(t\.me/\+\.\.\.\) cannot be resolved by a bot: use the link of a post in the channel or the -100\.\.\. chat ID$"


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
        "https://t.me/meucanal/123",  # link de post de canal público
        "t.me/meucanal/123/",
    ],
)
def test_identifier_accepts_username_public_link_and_public_post_link(raw):
    assert ChatIdentifier.parse(raw).as_chat_id() == "@meucanal"


@pytest.mark.parametrize(
    "raw",
    [
        "https://t.me/c/1234567890/15",  # "Copiar link" de um post de canal privado
        "http://t.me/c/1234567890/15/",
        "t.me/c/1234567890",
        "T.ME/C/1234567890/15",
        "https://telegram.me/c/1234567890/15",
        "  -1001234567890  ",
        "-1001234567890",
    ],
)
def test_identifier_converts_private_post_link_and_accepts_channel_id(raw):
    assert ChatIdentifier.parse(raw).as_chat_id() == "-1001234567890"


@pytest.mark.parametrize("raw", ["https://t.me/+AbCdEf123", "t.me/+AbCdEf123", "https://t.me/joinchat/AbCdEf123", "T.ME/JOINCHAT/x"])
def test_identifier_explains_that_invite_links_cannot_be_resolved(raw):
    with pytest.raises(ValueError, match=INVITE):
        ChatIdentifier.parse(raw)


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
        "https://evil.example/meucanal",
        "https://evil.example/c/1234567890/15",
        "https://t.me/c/12345678/15",  # id curto demais para -100 + 9 dígitos
        "https://t.me/c/abc/15",
        "https://t.me/meucanal/abc",
        "-123456789",  # grupo comum não vira Channel
        "-100123",
        "1001234567890",
    ],
)
def test_identifier_rejects_everything_else(raw):
    with pytest.raises(ValueError, match=INVALID):
        ChatIdentifier.parse(raw)


def test_identifier_accepts_limits_of_username_length():
    assert ChatIdentifier.parse("@" + "a" * 5).as_chat_id() == "@aaaaa"
    assert ChatIdentifier.parse("@" + "a" * 32).as_chat_id() == "@" + "a" * 32
    assert ChatIdentifier.parse("@canal_123").as_chat_id() == "@canal_123"


@pytest.mark.parametrize("value", ["x", "meucanal", "@abcd", "@meucanal\n", "-123", "-1001234567890\n", "@-1001234567890"])
def test_identifier_validates_when_built_directly(value):
    with pytest.raises(ValueError, match=INVALID):
        ChatIdentifier(value)


def test_identifier_built_directly_keeps_a_valid_value():
    assert ChatIdentifier("@meucanal").as_chat_id() == "@meucanal"
    assert ChatIdentifier("-1001234567890").as_chat_id() == "-1001234567890"


def test_identifier_is_immutable():
    identifier = ChatIdentifier.parse("@meucanal")
    with pytest.raises(AttributeError):
        identifier.value = "@outrocanal"  # type: ignore[misc]


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
        DiscoveredChat(chat_id="-1001234567890\n", title="X", chat_type="channel")
    assert DiscoveredChat(chat_id="-123", title="X", chat_type="group").is_registrable is False


def test_discovered_chat_is_not_a_forum_by_default():
    defaults = {f.name: f.default for f in dataclasses.fields(DiscoveredChat)}
    assert defaults["is_forum"] is False
    forum = DiscoveredChat(chat_id="-1009876543210", title="Grupo", chat_type="supergroup", is_forum=True)
    assert forum.is_forum is True


@pytest.mark.parametrize("raw, expected", [("channel", ChatType.CHANNEL), ("supergroup", ChatType.SUPERGROUP), ("group", ChatType.GROUP)])
def test_discovered_chat_kind_maps_the_telegram_type(raw, expected):
    chat_id = "-123456789" if raw == "group" else "-1001234567890"
    assert DiscoveredChat(chat_id=chat_id, title="X", chat_type=raw).kind is expected
