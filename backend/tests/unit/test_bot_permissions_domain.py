import dataclasses
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest
from src.domain.channels.bot_permissions import BotMemberStatus, BotPermissions, SendPermissions
from src.domain.channels.channel import ChatType

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
ALL = SendPermissions(can_send_messages=True, can_send_photos=True, can_send_videos=True, can_send_polls=True)
NONE = SendPermissions()
ONLY_TEXT = SendPermissions(can_send_messages=True)


def sends(p: BotPermissions) -> tuple[bool, bool, bool, bool]:
    return (p.can_send_messages, p.can_send_photos, p.can_send_videos, p.can_send_polls)


def evaluate(chat_type=ChatType.SUPERGROUP, status=BotMemberStatus.MEMBER, *, can_post_messages=False,
             own=None, chat_default=NONE, is_forum=False):
    return BotPermissions.evaluate(
        chat_type=chat_type,
        is_forum=is_forum,
        bot_status=status,
        can_post_messages=can_post_messages,
        own=own,
        chat_default=chat_default,
        checked_at=NOW,
    )


def test_send_permissions_default_to_nothing_allowed():
    assert {f.name: f.default for f in dataclasses.fields(SendPermissions)} == {
        "can_send_messages": False,
        "can_send_photos": False,
        "can_send_videos": False,
        "can_send_polls": False,
    }


def test_send_permissions_are_immutable():
    with pytest.raises(FrozenInstanceError):
        ALL.can_send_messages = False


def test_bot_member_status_values_are_the_telegram_ones():
    assert [s.value for s in BotMemberStatus] == ["creator", "administrator", "member", "restricted", "left", "kicked"]


@pytest.mark.parametrize("chat_type", [ChatType.CHANNEL, ChatType.SUPERGROUP])
def test_creator_can_send_everything(chat_type):
    assert sends(evaluate(chat_type, BotMemberStatus.CREATOR)) == (True, True, True, True)


def test_channel_admin_with_post_permission_can_send_everything():
    p = evaluate(ChatType.CHANNEL, BotMemberStatus.ADMINISTRATOR, can_post_messages=True, chat_default=NONE)
    assert sends(p) == (True, True, True, True)


def test_channel_admin_without_post_permission_can_send_nothing():
    assert sends(evaluate(ChatType.CHANNEL, BotMemberStatus.ADMINISTRATOR, chat_default=ALL)) == (False,) * 4


def test_group_admin_is_not_limited_by_the_group_defaults():
    # Administrador de grupo não segue as permissões padrão dos membros.
    assert sends(evaluate(ChatType.SUPERGROUP, BotMemberStatus.ADMINISTRATOR, chat_default=NONE)) == (True,) * 4


def test_group_member_follows_the_group_defaults():
    p = evaluate(chat_default=SendPermissions(can_send_messages=True, can_send_videos=True))
    assert sends(p) == (True, False, True, False)


def test_channel_member_cannot_send():
    assert sends(evaluate(ChatType.CHANNEL, BotMemberStatus.MEMBER, can_post_messages=True, chat_default=ALL)) == (False,) * 4


def test_restricted_bot_needs_both_its_own_and_the_group_permission():
    own = SendPermissions(can_send_messages=True, can_send_photos=True, can_send_polls=True)
    group = SendPermissions(can_send_messages=True, can_send_photos=False, can_send_videos=True, can_send_polls=True)
    p = evaluate(status=BotMemberStatus.RESTRICTED, own=own, chat_default=group)
    assert sends(p) == (True, False, False, True)


@pytest.mark.parametrize(
    "own, group",
    [(ALL, NONE), (NONE, ALL)],
    ids=["group-forbids", "bot-restricted"],
)
def test_restricted_bot_is_denied_when_either_side_forbids(own, group):
    assert sends(evaluate(status=BotMemberStatus.RESTRICTED, own=own, chat_default=group)) == (False,) * 4


def test_restricted_bot_without_own_permissions_can_send_nothing():
    assert sends(evaluate(status=BotMemberStatus.RESTRICTED, own=None, chat_default=ALL)) == (False,) * 4


def test_restricted_bot_in_a_channel_cannot_send():
    assert sends(evaluate(ChatType.CHANNEL, BotMemberStatus.RESTRICTED, own=ALL, chat_default=ALL)) == (False,) * 4


@pytest.mark.parametrize("status", [BotMemberStatus.LEFT, BotMemberStatus.KICKED])
@pytest.mark.parametrize("chat_type", [ChatType.CHANNEL, ChatType.SUPERGROUP])
def test_bot_outside_the_chat_can_send_nothing(status, chat_type):
    assert sends(evaluate(chat_type, status, can_post_messages=True, own=ALL, chat_default=ALL)) == (False,) * 4


def test_evaluate_keeps_the_chat_kind_status_and_time():
    p = evaluate(ChatType.SUPERGROUP, BotMemberStatus.MEMBER, is_forum=True, chat_default=ONLY_TEXT)
    assert (p.chat_type, p.is_forum, p.bot_status, p.checked_at) == (
        ChatType.SUPERGROUP, True, BotMemberStatus.MEMBER, NOW,
    )


def test_outside_chat_keeps_the_known_kind_and_allows_nothing():
    p = BotPermissions.outside_chat(chat_type=ChatType.CHANNEL, is_forum=False, checked_at=NOW)
    assert (p.chat_type, p.is_forum, p.bot_status, p.checked_at) == (ChatType.CHANNEL, False, BotMemberStatus.LEFT, NOW)
    assert sends(p) == (False,) * 4


def test_outside_chat_accepts_a_channel_without_known_type():
    # Canal vinculado antes da #99 ainda não tem tipo salvo.
    p = BotPermissions.outside_chat(chat_type=None, is_forum=False, checked_at=NOW)
    assert p.chat_type is None


def test_bot_permissions_are_immutable():
    p = evaluate()
    with pytest.raises(FrozenInstanceError):
        p.can_send_messages = True


def test_bot_permissions_defaults_allow_nothing():
    defaults = {f.name: f.default for f in dataclasses.fields(BotPermissions) if f.name.startswith("can_")}
    assert defaults == {
        "can_send_messages": False,
        "can_send_photos": False,
        "can_send_videos": False,
        "can_send_polls": False,
    }


@pytest.mark.parametrize("checked_at", [datetime(2026, 10, 28, 12, 0), datetime(2026, 10, 28, 9, 0, tzinfo=timezone(timedelta(hours=-3)))])
def test_checked_at_must_be_utc(checked_at):
    with pytest.raises(ValueError, match=r"^checked_at must be in UTC$"):
        BotPermissions(chat_type=ChatType.CHANNEL, is_forum=False, bot_status=BotMemberStatus.LEFT, checked_at=checked_at)


def test_basic_group_has_no_bot_permissions():
    with pytest.raises(ValueError, match=r"^A basic group cannot be registered: convert it to a supergroup first$"):
        evaluate(ChatType.GROUP)


def test_only_supergroups_can_be_forums():
    with pytest.raises(ValueError, match=r"^Only supergroups can be forums$"):
        evaluate(ChatType.CHANNEL, is_forum=True)
