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


def test_channel_defaults_for_topic_fields():
    # Issue #101: canais sem tópico têm message_thread_id e topic_name como None
    defaults = {f.name: f.default for f in dataclasses.fields(Channel) if f.name in ("message_thread_id", "topic_name")}
    assert defaults == {"message_thread_id": None, "topic_name": None}
    c = _channel()
    assert c.message_thread_id is None
    assert c.topic_name is None
    assert c.destination_id == "-1001234567890"


def test_channel_with_valid_topic():
    c = _channel(message_thread_id=45, topic_name="Anúncios")
    assert c.message_thread_id == 45
    assert c.topic_name == "Anúncios"
    assert c.destination_id == "-1001234567890:45"


def test_channel_normalizes_empty_topic_name_to_none():
    c = _channel(message_thread_id=45, topic_name="   ")
    assert c.topic_name is None


def test_channel_allows_message_thread_id_1():
    # Tópico 1 é o tópico Geral padrão em fóruns do Telegram; deve ser aceito
    c = _channel(message_thread_id=1, topic_name="General")
    assert c.message_thread_id == 1
    assert c.destination_id == "-1001234567890:1"


@pytest.mark.parametrize("invalid_thread_id", [0, -1, -45, "abc", "45", True, False, 45.5])
def test_channel_rejects_non_positive_message_thread_id(invalid_thread_id):
    with pytest.raises(ValueError, match=r"^message_thread_id must be a positive integer$"):
        _channel(message_thread_id=invalid_thread_id)


def test_set_topic():
    c = _channel(chat_type=ChatType.SUPERGROUP, is_forum=True)
    c.set_topic(45, "Anúncios")
    assert (c.message_thread_id, c.topic_name) == (45, "Anúncios")
    c.set_topic(1, "General")
    assert (c.message_thread_id, c.topic_name) == (1, "General")
    with pytest.raises(ValueError, match=r"^message_thread_id must be a positive integer$"):
        c.set_topic(0, "Invalid")
    with pytest.raises(ValueError, match=r"^message_thread_id must be a positive integer$"):
        c.set_topic("45", "Invalid")
    with pytest.raises(ValueError, match=r"^message_thread_id must be a positive integer$"):
        c.set_topic(True, "Invalid")
    c.set_topic(None, None)
    assert (c.message_thread_id, c.topic_name) == (None, None)


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
    c = _channel(chat_type=ChatType.SUPERGROUP, is_forum=True, message_thread_id=45, topic_name="Anúncios")
    c.relink("-1009876543210")
    assert (c.chat_id, c.chat_type, c.is_forum, c.message_thread_id, c.topic_name) == ("-1009876543210", None, False, None, None)


def test_relink_rejects_an_invalid_chat_id_and_keeps_the_channel():
    c = _channel(chat_type=ChatType.CHANNEL)
    with pytest.raises(ValueError, match=r"^Invalid Telegram Channel Chat ID format \(must start with -100 followed by digits\)$"):
        c.relink("-123456789")
    assert (c.chat_id, c.chat_type) == ("-1001234567890", ChatType.CHANNEL)
