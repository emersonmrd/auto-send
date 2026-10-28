import dataclasses

import pytest
from src.domain.channels.channel import Channel, ChatType

def test_should_create_valid_channel():
    c = Channel(
        id="c-1",
        profile_id="p-1",
        title="Canal de Novidades",
        chat_id="-1001234567890",
        invite_link="https://t.me/+xyz",
    )
    assert c.id == "c-1"
    assert c.title == "Canal de Novidades"
    assert c.chat_id == "-1001234567890"
    assert c.is_active is True

def test_should_fail_when_chat_id_is_invalid():
    with pytest.raises(ValueError, match="Invalid Telegram Channel Chat ID format"):
        Channel(
            id="c-2",
            profile_id="p-1",
            title="Invalid",
            chat_id="123456",
        )

    with pytest.raises(ValueError, match="Invalid Telegram Channel Chat ID format"):
        Channel(
            id="c-3",
            profile_id="p-1",
            title="Invalid",
            chat_id="-200123456789",
        )


def _channel(**overrides):
    fields = {"id": "c-1", "profile_id": "p-1", "title": "Canal de Novidades", "chat_id": "-1001234567890"}
    fields.update(overrides)
    return Channel(**fields)


def test_chat_type_values_mirror_the_telegram_chat_kinds():
    assert [t.value for t in ChatType] == ["channel", "supergroup", "group"]


def test_channel_without_classification_has_unknown_chat_type_and_no_forum():
    # Canais vinculados antes da #99 ficam sem tipo até a próxima edição.
    defaults = {f.name: f.default for f in dataclasses.fields(Channel) if f.name in ("chat_type", "is_forum")}
    assert defaults == {"chat_type": None, "is_forum": False}
    assert _channel().chat_type is None


@pytest.mark.parametrize(
    "chat_type, is_forum",
    [(ChatType.CHANNEL, False), (ChatType.SUPERGROUP, False), (ChatType.SUPERGROUP, True)],
)
def test_channel_accepts_channel_supergroup_and_forum(chat_type, is_forum):
    c = _channel(chat_type=chat_type, is_forum=is_forum)
    assert (c.chat_type, c.is_forum) == (chat_type, is_forum)


def test_basic_group_cannot_become_a_channel():
    with pytest.raises(ValueError, match=r"^A basic group cannot be registered: convert it to a supergroup first$"):
        _channel(chat_type=ChatType.GROUP)


@pytest.mark.parametrize("chat_type", [None, ChatType.CHANNEL])
def test_only_supergroups_can_be_forums(chat_type):
    with pytest.raises(ValueError, match=r"^Only supergroups can be forums$"):
        _channel(chat_type=chat_type, is_forum=True)


def test_classify_records_the_kind_reported_by_telegram():
    c = _channel()
    c.classify(ChatType.SUPERGROUP, is_forum=True)
    assert (c.chat_type, c.is_forum) == (ChatType.SUPERGROUP, True)


def test_classify_rejects_an_invalid_kind_and_keeps_the_previous_one():
    c = _channel(chat_type=ChatType.CHANNEL)
    with pytest.raises(ValueError, match=r"^Only supergroups can be forums$"):
        c.classify(ChatType.CHANNEL, is_forum=True)
    with pytest.raises(ValueError, match=r"^A basic group cannot be registered: convert it to a supergroup first$"):
        c.classify(ChatType.GROUP, is_forum=False)
    assert (c.chat_type, c.is_forum) == (ChatType.CHANNEL, False)


def test_relink_moves_to_the_new_chat_and_forgets_the_old_kind():
    c = _channel(chat_type=ChatType.SUPERGROUP, is_forum=True)
    c.relink("-1009876543210")
    assert (c.chat_id, c.chat_type, c.is_forum) == ("-1009876543210", None, False)


def test_relink_rejects_an_invalid_chat_id_and_keeps_the_channel():
    c = _channel(chat_type=ChatType.CHANNEL)
    with pytest.raises(ValueError, match=r"^Invalid Telegram Channel Chat ID format \(must start with -100 followed by digits\)$"):
        c.relink("-123456789")
    assert (c.chat_id, c.chat_type) == ("-1001234567890", ChatType.CHANNEL)
