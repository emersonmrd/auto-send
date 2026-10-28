import dataclasses
from datetime import datetime, timezone
import pytest
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastPoll,
    BroadcastStatus,
    ChannelDeliveryResult,
    DeliveryFailureCategory,
    DispatchStrategy,
    InlineButton,
    MediaAttachment,
    MediaType,
    PollType,
    validate_and_escape_telegram_html,
)

def test_should_choose_single_message_strategy_when_text_le_1024_and_has_media():
    button = InlineButton(text="Learn more", url="https://t.me/news")
    media = MediaAttachment(file_path="/tmp/video.mp4", media_type=MediaType.VIDEO, file_size=1024)
    
    msg = BroadcastMessage(
        id="broadcast-1",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="A" * 500,
        media=media,
        button=button,
    )
    
    assert msg.get_dispatch_strategy() == DispatchStrategy.SINGLE_MEDIA_WITH_CAPTION
    assert msg.status == BroadcastStatus.PENDING

def test_should_choose_single_message_strategy_at_exact_1024_boundary():
    media = MediaAttachment(file_path="/tmp/video.mp4", media_type=MediaType.VIDEO, file_size=1024)
    msg = BroadcastMessage(
        id="broadcast-boundary",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="A" * 1024,
        media=media,
    )
    assert msg.get_dispatch_strategy() == DispatchStrategy.SINGLE_MEDIA_WITH_CAPTION

def test_should_choose_split_message_strategy_when_text_gt_1024_and_has_media():
    media = MediaAttachment(file_path="/tmp/video.mp4", media_type=MediaType.VIDEO, file_size=1024)
    
    msg = BroadcastMessage(
        id="broadcast-2",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="A" * 1025,
        media=media,
    )
    
    assert msg.get_dispatch_strategy() == DispatchStrategy.SPLIT_TEXT_THEN_MEDIA

def test_should_choose_text_only_strategy_when_no_media():
    msg = BroadcastMessage(
        id="broadcast-3",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="A" * 200,
    )
    
    assert msg.get_dispatch_strategy() == DispatchStrategy.TEXT_ONLY

def test_should_reject_button_url_with_private_or_unsafe_protocols():
    with pytest.raises(ValueError, match="Insecure or invalid URL scheme"):
        InlineButton(text="Click", url="http://127.0.0.1:8000/admin")
        
    with pytest.raises(ValueError, match="Insecure or invalid URL scheme"):
        InlineButton(text="Click", url="file:///etc/passwd")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme"):
        InlineButton(text="Click", url="http://google.com")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme: Private network prohibited"):
        InlineButton(text="Click", url="https://localhost/api")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme: Private network prohibited"):
        InlineButton(text="Click", url="https://127.0.0.1/api")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme: Private network prohibited"):
        InlineButton(text="Click", url="https://0.0.0.0/api")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme: Private IP prohibited"):
        InlineButton(text="Click", url="https://192.168.1.1/api")

    with pytest.raises(ValueError, match="Insecure or invalid URL scheme: Private IP prohibited"):
        InlineButton(text="Click", url="https://10.0.0.1/api")

def test_should_accept_valid_public_https_button_url():
    btn = InlineButton(text="Join", url="https://t.me/+joinlink")
    assert btn.text == "Join"
    assert btn.url == "https://t.me/+joinlink"

def test_cancel_broadcast_lifecycle():
    msg = BroadcastMessage(
        id="b-1",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.PENDING,
    )
    msg.cancel()
    assert msg.status == BroadcastStatus.CANCELLED

    msg_scheduled = BroadcastMessage(
        id="b-2",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.SCHEDULED,
    )
    msg_scheduled.cancel()
    assert msg_scheduled.status == BroadcastStatus.CANCELLED

    msg_dispatching = BroadcastMessage(
        id="b-3",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.DISPATCHING,
    )
    with pytest.raises(ValueError, match="Cannot cancel an in-flight or completed broadcast"):
        msg_dispatching.cancel()

    msg_completed = BroadcastMessage(
        id="b-4",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.COMPLETED,
    )
    with pytest.raises(ValueError, match="Cannot cancel an in-flight or completed broadcast"):
        msg_completed.cancel()

def test_reschedule_broadcast_lifecycle():
    now = datetime.now(timezone.utc)
    new_date = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
    
    msg_pending = BroadcastMessage(
        id="b-5",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.PENDING,
        scheduled_at=now,
    )
    msg_pending.reschedule(new_date)
    assert msg_pending.scheduled_at == new_date
    assert msg_pending.status == BroadcastStatus.SCHEDULED

    msg_scheduled = BroadcastMessage(
        id="b-6",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Hello",
        status=BroadcastStatus.SCHEDULED,
        scheduled_at=now,
    )
    msg_scheduled.reschedule(new_date)
    assert msg_scheduled.scheduled_at == new_date
    assert msg_scheduled.status == BroadcastStatus.SCHEDULED

    for invalid_status in [BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED, BroadcastStatus.CANCELLED]:
        msg_invalid = BroadcastMessage(
            id="b-inv",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Hello",
            status=invalid_status,
        )
        with pytest.raises(ValueError, match="Cannot reschedule an in-flight, completed, or cancelled broadcast"):
            msg_invalid.reschedule(new_date)

def test_update_content_broadcast_lifecycle():
    msg = BroadcastMessage(
        id="b-7",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Initial text",
        status=BroadcastStatus.PENDING,
    )
    new_button = InlineButton(text="Updated", url="https://t.me/updated")
    msg.update_content("Updated text", new_button)
    assert msg.text == "Updated text"
    assert msg.button == new_button

    msg.update_content("Only text updated", None)
    assert msg.text == "Only text updated"
    assert msg.button is None

    for invalid_status in [BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED, BroadcastStatus.CANCELLED]:
        msg_invalid = BroadcastMessage(
            id="b-inv-upd",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Hello",
            status=invalid_status,
        )
        with pytest.raises(ValueError, match="Cannot update content of an in-flight, completed, or cancelled broadcast"):
            msg_invalid.update_content("New text")

@pytest.mark.asyncio
async def test_in_memory_repository_get_scheduled_by_profile():
    from src.infrastructure.in_memory_broadcast_repository import InMemoryBroadcastRepository
    
    repo = InMemoryBroadcastRepository()
    d1 = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    d3 = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)
    d4 = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)

    # b1: profile-1, SCHEDULED, d1
    b1 = BroadcastMessage(id="b1", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.SCHEDULED, scheduled_at=d1)
    # b2: profile-1, PENDING, d2 (earlier)
    b2 = BroadcastMessage(id="b2", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.PENDING, scheduled_at=d2)
    # b3: profile-1, CANCELLED, d3 (should be excluded)
    b3 = BroadcastMessage(id="b3", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.CANCELLED, scheduled_at=d3)
    # b4: profile-1, COMPLETED (should be excluded)
    b4 = BroadcastMessage(id="b4", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.COMPLETED, scheduled_at=d1)
    # b5: profile-2, SCHEDULED, d2 (different profile)
    b5 = BroadcastMessage(id="b5", profile_id="m2", target_channel_ids=["-1001"], status=BroadcastStatus.SCHEDULED, scheduled_at=d2)
    # b6: profile-1, SCHEDULED, scheduled_at is None (should be excluded)
    b6 = BroadcastMessage(id="b6", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.SCHEDULED, scheduled_at=None)
    # b7: profile-1, MISFIRED, d4 (deve aparecer primeiro na fila antes dos SCHEDULED/PENDING)
    b7 = BroadcastMessage(id="b7", profile_id="m1", target_channel_ids=["-1001"], status=BroadcastStatus.MISFIRED, scheduled_at=d4)

    for b in [b1, b2, b3, b4, b5, b6, b7]:
        await repo.save(b)

    scheduled_m1 = await repo.get_scheduled_by_profile("m1")
    assert [b.id for b in scheduled_m1] == ["b7", "b2", "b1"]


def test_misfired_transitions_and_guards():
    now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    future = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)

    for valid_status in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED):
        msg = BroadcastMessage(
            id="b-m",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Bom dia",
            status=valid_status,
            scheduled_at=now,
        )
        msg.mark_misfired()
        assert msg.status is BroadcastStatus.MISFIRED

    # De MISFIRED -> SCHEDULED via reschedule, podendo editar conteúdo antes
    msg_resched = BroadcastMessage(
        id="b-m-resched",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Bom dia",
        status=BroadcastStatus.MISFIRED,
        scheduled_at=now,
    )
    msg_resched.update_content("Boa tarde", None)
    msg_resched.reschedule(future)
    assert msg_resched.status is BroadcastStatus.SCHEDULED
    assert msg_resched.scheduled_at == future
    assert msg_resched.text == "Boa tarde"

    # De MISFIRED -> DISPATCHING via start_dispatch
    for dispatchable in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED, BroadcastStatus.MISFIRED):
        msg_disp = BroadcastMessage(
            id="b-m-disp",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Envio imediato",
            status=dispatchable,
            scheduled_at=now,
        )
        msg_disp.start_dispatch()
        assert msg_disp.status is BroadcastStatus.DISPATCHING

    # De MISFIRED -> CANCELLED via cancel
    msg_cancel = BroadcastMessage(
        id="b-m-cancel",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Descartar",
        status=BroadcastStatus.MISFIRED,
        scheduled_at=now,
    )
    msg_cancel.cancel()
    assert msg_cancel.status is BroadcastStatus.CANCELLED

    # Guardas de estados não permitidos para mark_misfired
    for invalid_misfire_status in (
        BroadcastStatus.MISFIRED,
        BroadcastStatus.DISPATCHING,
        BroadcastStatus.COMPLETED,
        BroadcastStatus.PARTIALLY_COMPLETED,
        BroadcastStatus.FAILED,
        BroadcastStatus.CANCELLED,
    ):
        invalid_msg = BroadcastMessage(
            id="b-inv-m",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Inv",
            status=invalid_misfire_status,
        )
        with pytest.raises(ValueError, match=r"^Only pending or scheduled broadcasts can become misfired$"):
            invalid_msg.mark_misfired()

    # Guardas de estados terminais/em voo para start_dispatch
    for invalid_dispatch_status in (
        BroadcastStatus.DISPATCHING,
        BroadcastStatus.COMPLETED,
        BroadcastStatus.PARTIALLY_COMPLETED,
        BroadcastStatus.FAILED,
        BroadcastStatus.CANCELLED,
    ):
        invalid_msg = BroadcastMessage(
            id="b-inv-d",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            text="Inv",
            status=invalid_dispatch_status,
        )
        with pytest.raises(ValueError, match=r"^Cannot dispatch an in-flight, completed, failed, or cancelled broadcast$"):
            invalid_msg.start_dispatch()


def test_remove_and_replace_target_channel_on_broadcast_message():
    for active_status in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED, BroadcastStatus.MISFIRED):
        msg = BroadcastMessage(
            id="b-rem",
            profile_id="p-1",
            target_channel_ids=["-1001111111111", "-1002222222222"],
            text="Multi-channel",
            status=active_status,
        )
        assert msg.is_pending_or_scheduled() is True
        # Canal que não está na lista retorna False sem alterar nada
        assert msg.remove_target_channel("-1009999999999") is False
        assert msg.target_channel_ids == ["-1001111111111", "-1002222222222"]
        assert msg.status is active_status

        # Remover um canal quando há outro mantém o status e reduz a lista
        assert msg.remove_target_channel("-1001111111111") is True
        assert msg.target_channel_ids == ["-1002222222222"]
        assert msg.status is active_status

        # Remover o último canal cancela o agendamento
        assert msg.remove_target_channel("-1002222222222") is True
        assert msg.target_channel_ids == []
        assert msg.status is BroadcastStatus.CANCELLED
        assert msg.is_pending_or_scheduled() is False

    # Substituir canal preserva ordem e desduplica se o novo já estiver presente
    for active_status in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED, BroadcastStatus.MISFIRED):
        msg_rep = BroadcastMessage(
            id="b-rep",
            profile_id="p-1",
            target_channel_ids=["-1001111111111", "-1002222222222"],
            text="Replace test",
            status=active_status,
        )
        assert msg_rep.replace_target_channel("-1001111111111", "-1001111111111") is False
        assert msg_rep.replace_target_channel("-1009999999999", "-1003333333333") is False
        assert msg_rep.replace_target_channel("-1001111111111", "-1003333333333") is True
        assert msg_rep.target_channel_ids == ["-1003333333333", "-1002222222222"]
        # Se substituir pelo outro canal que já está na lista, não duplica
        assert msg_rep.replace_target_channel("-1003333333333", "-1002222222222") is True
        assert msg_rep.target_channel_ids == ["-1002222222222"]

    # Bloqueio em DISPATCHING
    msg_disp = BroadcastMessage(
        id="b-disp",
        profile_id="p-1",
        target_channel_ids=["-1001111111111"],
        status=BroadcastStatus.DISPATCHING,
    )
    assert msg_disp.is_pending_or_scheduled() is False
    with pytest.raises(
        ValueError,
        match=r"^There is a broadcast currently dispatching\. Wait for it to finish and try again\.$",
    ):
        msg_disp.remove_target_channel("-1001111111111")
    with pytest.raises(
        ValueError,
        match=r"^There is a broadcast currently dispatching\. Wait for it to finish and try again\.$",
    ):
        msg_disp.replace_target_channel("-1001111111111", "-1002222222222")

    # Bloqueio em estados terminais
    for terminal_status in (
        BroadcastStatus.COMPLETED,
        BroadcastStatus.PARTIALLY_COMPLETED,
        BroadcastStatus.FAILED,
        BroadcastStatus.CANCELLED,
    ):
        msg_term = BroadcastMessage(
            id="b-term",
            profile_id="p-1",
            target_channel_ids=["-1001111111111"],
            status=terminal_status,
        )
        assert msg_term.is_pending_or_scheduled() is False
        with pytest.raises(
            ValueError,
            match=r"^Cannot modify target channels of a completed, failed, or cancelled broadcast$",
        ):
            msg_term.remove_target_channel("-1001111111111")
        with pytest.raises(
            ValueError,
            match=r"^Cannot modify target channels of a completed, failed, or cancelled broadcast$",
        ):
            msg_term.replace_target_channel("-1001111111111", "-1002222222222")


def _dispatching_broadcast(targets: int) -> BroadcastMessage:
    ids = [f"-100123456789{i}" for i in range(targets)]
    return BroadcastMessage(id="b", profile_id="p", target_channel_ids=ids, status=BroadcastStatus.DISPATCHING)


def test_finish_dispatch_completes_when_every_channel_received():
    msg = _dispatching_broadcast(3)
    msg.finish_dispatch(delivered=3, total=3)
    assert msg.status is BroadcastStatus.COMPLETED


def test_finish_dispatch_is_partial_when_some_channels_received():
    msg = _dispatching_broadcast(3)
    msg.finish_dispatch(delivered=1, total=3)
    assert msg.status is BroadcastStatus.PARTIALLY_COMPLETED
    msg = _dispatching_broadcast(3)
    msg.finish_dispatch(delivered=2, total=3)
    assert msg.status is BroadcastStatus.PARTIALLY_COMPLETED


def test_finish_dispatch_fails_when_no_channel_received():
    msg = _dispatching_broadcast(3)
    msg.finish_dispatch(delivered=0, total=3)
    assert msg.status is BroadcastStatus.FAILED


def test_finish_dispatch_rejects_impossible_counts():
    with pytest.raises(ValueError, match=r"^delivered must be between 0 and total$"):
        _dispatching_broadcast(2).finish_dispatch(delivered=3, total=2)
    with pytest.raises(ValueError, match=r"^delivered must be between 0 and total$"):
        _dispatching_broadcast(2).finish_dispatch(delivered=-1, total=2)


def test_channel_delivery_result_and_finish_dispatch_with_results():
    ok = ChannelDeliveryResult.success("-1001111111111")
    assert ok.chat_id == "-1001111111111"
    assert ok.delivered is True
    assert ok.failure_category is None
    assert ok.detail is None

    fail = ChannelDeliveryResult.failure(
        "-1002222222222",
        category=DeliveryFailureCategory.NO_POST_PERMISSION,
        detail="not enough rights",
    )
    assert fail.chat_id == "-1002222222222"
    assert fail.delivered is False
    assert fail.failure_category is DeliveryFailureCategory.NO_POST_PERMISSION
    assert fail.detail == "not enough rights"

    fail_no_detail = ChannelDeliveryResult.failure(
        "-1003333333333",
        category=DeliveryFailureCategory.INVALID_TOKEN,
    )
    assert fail_no_detail.detail is None

    for empty_id in ("", "   "):
        with pytest.raises(ValueError, match=r"^chat_id cannot be empty$"):
            ChannelDeliveryResult(chat_id=empty_id, delivered=True)

    with pytest.raises(ValueError, match=r"^Delivered result cannot have a failure_category$"):
        ChannelDeliveryResult(
            chat_id="-1001111111111",
            delivered=True,
            failure_category=DeliveryFailureCategory.OTHER,
        )

    with pytest.raises(ValueError, match=r"^Failed delivery result requires a failure_category$"):
        ChannelDeliveryResult(chat_id="-1001111111111", delivered=False)

    # Cálculo de status por finish_dispatch_with_results
    msg_partial = BroadcastMessage(
        id="b-res-partial",
        profile_id="p-1",
        target_channel_ids=["-1001111111111", "-1002222222222"],
        status=BroadcastStatus.DISPATCHING,
    )
    msg_partial.finish_dispatch_with_results([ok, fail])
    assert msg_partial.status is BroadcastStatus.PARTIALLY_COMPLETED
    assert msg_partial.delivery_results == [ok, fail]

    msg_all_ok = BroadcastMessage(
        id="b-res-ok",
        profile_id="p-1",
        target_channel_ids=["-1001111111111"],
        status=BroadcastStatus.DISPATCHING,
    )
    msg_all_ok.finish_dispatch_with_results([ok])
    assert msg_all_ok.status is BroadcastStatus.COMPLETED
    assert msg_all_ok.delivery_results == [ok]

    msg_fail_all = BroadcastMessage(
        id="b-res-fail",
        profile_id="p-1",
        target_channel_ids=["-1001111111111", "-1002222222222"],
        status=BroadcastStatus.DISPATCHING,
    )
    msg_fail_all.fail_all_channels(
        DeliveryFailureCategory.INVALID_TOKEN,
        detail="Unauthorized",
    )
    assert msg_fail_all.status is BroadcastStatus.FAILED
    assert len(msg_fail_all.delivery_results) == 2
    assert all(
        r.delivered is False
        and r.failure_category is DeliveryFailureCategory.INVALID_TOKEN
        and r.detail == "Unauthorized"
        for r in msg_fail_all.delivery_results
    )
    assert [r.chat_id for r in msg_fail_all.delivery_results] == [
        "-1001111111111",
        "-1002222222222",
    ]


def test_validate_and_escape_telegram_html_allows_telegram_tags_and_escapes_plain_symbols():
    assert validate_and_escape_telegram_html("") == ""

    # Caracteres <, > e & fora de tags válidas são escapados sem quebrar
    assert (
        validate_and_escape_telegram_html("2 < 3 & Tom & Jerry > 1")
        == "2 &lt; 3 &amp; Tom &amp; Jerry &gt; 1"
    )
    # Idempotente se já estiver escapado
    assert (
        validate_and_escape_telegram_html("2 &lt; 3 &amp; Tom &quot;ok&quot; &#39;x&#39; &gt; 1")
        == "2 &lt; 3 &amp; Tom &quot;ok&quot; &#39;x&#39; &gt; 1"
    )

    # Todas as tags suportadas pelo Telegram
    for tag in (
        "b",
        "strong",
        "i",
        "em",
        "u",
        "ins",
        "s",
        "strike",
        "del",
        "code",
        "pre",
        "blockquote",
        "tg-spoiler",
    ):
        formatted = f"<{tag.upper()}>Texto &amp; 2 < 3</{tag.upper()}>"
        assert (
            validate_and_escape_telegram_html(formatted)
            == f"<{tag}>Texto &amp; 2 &lt; 3</{tag}>"
        )

    assert (
        validate_and_escape_telegram_html("<span class='tg-spoiler'>segredo</span>")
        == '<span class="tg-spoiler">segredo</span>'
    )
    assert (
        validate_and_escape_telegram_html('<SPAN class="tg-spoiler">segredo</SPAN>')
        == '<span class="tg-spoiler">segredo</span>'
    )

    # Links https:// válidos (aspas duplas ou simples, com query string escapada)
    assert (
        validate_and_escape_telegram_html(
            "Visite <a href='https://example.com/p?a=1&b=2'>Tom & Jerry</a>!"
        )
        == 'Visite <a href="https://example.com/p?a=1&amp;b=2">Tom &amp; Jerry</a>!'
    )
    assert (
        validate_and_escape_telegram_html(
            'Visite <A HREF="https://example.com/p?a=1&amp;b=2">Link</A>'
        )
        == 'Visite <a href="https://example.com/p?a=1&amp;b=2">Link</a>'
    )
    assert (
        validate_and_escape_telegram_html(
            'Visite <a href=\'https://example.com/p?q="teste"\'>Busca</a>'
        )
        == 'Visite <a href="https://example.com/p?q=&quot;teste&quot;">Busca</a>'
    )

    # BroadcastMessage aplica na criação e no update_content
    msg = BroadcastMessage(
        id="b-html",
        profile_id="p-1",
        target_channel_ids=["-1001111111111"],
        text='<b>Oferta</b> 2 < 3 & <a href="https://example.com">link</a>',
    )
    assert msg.text == '<b>Oferta</b> 2 &lt; 3 &amp; <a href="https://example.com">link</a>'
    msg.update_content("Tom & Jerry < 5")
    assert msg.text == "Tom &amp; Jerry &lt; 5"


@pytest.mark.parametrize(
    "invalid_html, expected_msg",
    [
        ("<script>alert(1)</script>", r"^Unsupported HTML tag in message$"),
        ("<div>bloco</div>", r"^Unsupported HTML tag in message$"),
        ("<img src=\"https://example.com/a.png\">", r"^Unsupported HTML tag in message$"),
        ("</script>", r"^Unsupported HTML tag in message$"),
        ("<span class=\"other\">x</span>", r"^Unsupported HTML tag in message$"),
        ("<a href=\"https://example.com\" onclick=\"x\">x</a>", r"^Unsupported HTML tag in message$"),
        ("<a>sem href</a>", r"^Unsupported HTML tag in message$"),
        ("<b class=\"x\">bold</b>", r"^Unsupported HTML tag in message$"),
        ("<b>sem fechar", r"^Invalid HTML formatting in message$"),
        ("</b>", r"^Invalid HTML formatting in message$"),
        ("<b><i>ordem errada</b></i>", r"^Invalid HTML formatting in message$"),
        ("Texto com <b sem fechar o sinal", r"^Invalid HTML formatting in message$"),
        ('<a href="http://example.com">inseguro</a>', r"^Insecure or invalid URL scheme\. Only https:// allowed\.$"),
        ('<a href="https://localhost/admin">local</a>', r"^Insecure or invalid URL scheme: Private network prohibited\.$"),
        ('<a href="https://192.168.1.1/admin">privado</a>', r"^Insecure or invalid URL scheme: Private IP prohibited\.$"),
    ],
)
def test_validate_and_escape_telegram_html_rejects_unsupported_tags_broken_markup_and_unsafe_links(
    invalid_html, expected_msg
):
    with pytest.raises(ValueError, match=expected_msg):
        validate_and_escape_telegram_html(invalid_html)
    with pytest.raises(ValueError, match=expected_msg):
        BroadcastMessage(
            id="b-bad",
            profile_id="p-1",
            target_channel_ids=["-1001111111111"],
            text=invalid_html,
        )



def _locked_candidate(status=BroadcastStatus.SCHEDULED, scheduled_at=None):
    from datetime import timedelta as _td
    return BroadcastMessage(
        id="b-lock",
        profile_id="p-1",
        target_channel_ids=["-1001111111111"],
        text="Lock",
        status=status,
        scheduled_at=scheduled_at or datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc),
    )


def test_edit_lock_acquire_renew_expire_and_release_before_schedule_keeps_broadcast():
    from datetime import timedelta
    from src.domain.broadcast.broadcast_message import DEFAULT_EDIT_LOCK_SECONDS

    assert DEFAULT_EDIT_LOCK_SECONDS == 90
    now = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)
    for status in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED, BroadcastStatus.MISFIRED):
        msg = _locked_candidate(status=status)
        assert msg.edit_locked_until is None
        assert msg.is_edit_locked(now) is False

        msg.acquire_edit_lock(now)
        assert msg.edit_locked_until == now + timedelta(seconds=90)
        assert msg.is_edit_locked(now) is True
        assert msg.is_edit_locked(now + timedelta(seconds=89)) is True
        assert msg.is_edit_locked(now + timedelta(seconds=90)) is False

        # Renovação estende a trava
        msg.acquire_edit_lock(now + timedelta(seconds=30), ttl=timedelta(seconds=60))
        assert msg.edit_locked_until == now + timedelta(seconds=90)

        # Antes de expirar, expire_overdue_edit_lock não faz nada
        assert msg.expire_overdue_edit_lock(now + timedelta(seconds=89)) is False
        assert msg.edit_locked_until is not None

        # Saiu sem salvar antes do horário: nada muda
        assert msg.release_edit_lock(now) is False
        assert msg.edit_locked_until is None
        assert msg.status is status

    # Sem trava, expire_overdue_edit_lock não faz nada
    msg = _locked_candidate()
    assert msg.expire_overdue_edit_lock(now) is False
    assert msg.status is BroadcastStatus.SCHEDULED


def test_edit_lock_release_or_expiry_after_schedule_cancels_and_reschedule_clears_lock():
    from datetime import timedelta

    sched = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)

    msg = _locked_candidate(scheduled_at=sched)
    msg.acquire_edit_lock(sched - timedelta(seconds=10))
    assert msg.release_edit_lock(sched) is True
    assert msg.status is BroadcastStatus.CANCELLED
    assert msg.edit_locked_until is None

    msg = _locked_candidate(scheduled_at=sched)
    msg.acquire_edit_lock(sched - timedelta(seconds=10), ttl=timedelta(seconds=30))
    assert msg.expire_overdue_edit_lock(sched + timedelta(seconds=20)) is True
    assert msg.status is BroadcastStatus.CANCELLED

    # Sem scheduled_at, liberar nunca cancela
    msg = BroadcastMessage(id="b", profile_id="p", target_channel_ids=["-1001111111111"], status=BroadcastStatus.PENDING)
    msg.acquire_edit_lock(sched)
    assert msg.release_edit_lock(sched + timedelta(days=1)) is False
    assert msg.status is BroadcastStatus.PENDING

    # Reagendar (salvar com horário novo) libera a trava
    msg = _locked_candidate(scheduled_at=sched)
    msg.acquire_edit_lock(sched - timedelta(seconds=10))
    msg.reschedule(sched + timedelta(hours=1))
    assert msg.edit_locked_until is None
    assert msg.scheduled_at == sched + timedelta(hours=1)


def test_edit_lock_rejects_terminal_states_and_non_positive_ttl():
    from datetime import timedelta

    now = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)
    for status in (
        BroadcastStatus.DISPATCHING,
        BroadcastStatus.COMPLETED,
        BroadcastStatus.PARTIALLY_COMPLETED,
        BroadcastStatus.FAILED,
        BroadcastStatus.CANCELLED,
    ):
        msg = _locked_candidate(status=status)
        with pytest.raises(ValueError, match=r"^Cannot lock an in-flight, completed, failed, or cancelled broadcast$"):
            msg.acquire_edit_lock(now)
        with pytest.raises(ValueError, match=r"^Cannot lock an in-flight, completed, failed, or cancelled broadcast$"):
            msg.release_edit_lock(now)

    msg = _locked_candidate()
    for bad_ttl in (timedelta(0), timedelta(seconds=-1)):
        with pytest.raises(ValueError, match=r"^ttl must be positive$"):
            msg.acquire_edit_lock(now, ttl=bad_ttl)
    assert msg.edit_locked_until is None
    msg.acquire_edit_lock(now, ttl=timedelta(microseconds=1))
    assert msg.edit_locked_until == now + timedelta(microseconds=1)


def test_update_target_channels_only_for_active_broadcasts_and_non_empty():
    for status in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED, BroadcastStatus.MISFIRED):
        msg = _locked_candidate(status=status)
        new_ids = ["-1002222222222", "-1003333333333"]
        msg.update_target_channels(new_ids)
        assert msg.target_channel_ids == new_ids
        assert msg.target_channel_ids is not new_ids
        with pytest.raises(ValueError, match=r"^target_channel_ids must be a non-empty list$"):
            msg.update_target_channels([])
        assert msg.target_channel_ids == new_ids

    for status in (BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED, BroadcastStatus.FAILED, BroadcastStatus.CANCELLED):
        msg = _locked_candidate(status=status)
        with pytest.raises(ValueError, match=r"^Cannot modify target channels of a completed, failed, or cancelled broadcast$"):
            msg.update_target_channels(["-1002222222222"])


def test_replace_media_and_remove_media_lifecycle():
    photo = MediaAttachment(file_path="/tmp/photo.jpg", media_type=MediaType.PHOTO, file_size=100)
    video = MediaAttachment(file_path="/tmp/video.mp4", media_type=MediaType.VIDEO, file_size=500)

    for active_status in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED, BroadcastStatus.MISFIRED):
        msg = _locked_candidate(status=active_status)
        assert msg.media is None
        assert msg.get_dispatch_strategy() == DispatchStrategy.TEXT_ONLY

        # Adicionar foto a um broadcast sem mídia
        msg.replace_media(photo)
        assert msg.media == photo
        assert msg.get_dispatch_strategy() == DispatchStrategy.SINGLE_MEDIA_WITH_CAPTION

        # Trocar foto por vídeo
        msg.replace_media(video)
        assert msg.media == video
        assert msg.get_dispatch_strategy() == DispatchStrategy.SINGLE_MEDIA_WITH_CAPTION

        # Remover mídia
        msg.remove_media()
        assert msg.media is None
        assert msg.get_dispatch_strategy() == DispatchStrategy.TEXT_ONLY

        # Remover novamente quando já é None não quebra
        msg.remove_media()
        assert msg.media is None


def test_replace_media_rejects_invalid_type_and_terminal_states():
    photo = MediaAttachment(file_path="/tmp/photo.jpg", media_type=MediaType.PHOTO, file_size=100)
    msg = _locked_candidate(status=BroadcastStatus.SCHEDULED)

    with pytest.raises(ValueError, match=r"^media must be a MediaAttachment instance$"):
        msg.replace_media("not-a-media-attachment")  # type: ignore

    with pytest.raises(ValueError, match=r"^media must be a MediaAttachment instance$"):
        msg.replace_media(None)  # type: ignore

    for term_status in (
        BroadcastStatus.DISPATCHING,
        BroadcastStatus.COMPLETED,
        BroadcastStatus.PARTIALLY_COMPLETED,
        BroadcastStatus.FAILED,
        BroadcastStatus.CANCELLED,
    ):
        msg = _locked_candidate(status=term_status)
        with pytest.raises(
            ValueError,
            match=r"^Cannot modify media of an in-flight, completed, failed, or cancelled broadcast$",
        ):
            msg.replace_media(photo)
        with pytest.raises(
            ValueError,
            match=r"^Cannot modify media of an in-flight, completed, failed, or cancelled broadcast$",
        ):
            msg.remove_media()


def _broadcast_with_status(status: BroadcastStatus) -> BroadcastMessage:
    return BroadcastMessage(
        id="b-abort",
        profile_id="p-1",
        target_channel_ids=["-1001234567890", "-1001234567891"],
        text="Hello",
        status=status,
    )


def test_abort_dispatch_cancels_in_flight_broadcast_and_keeps_partial_results():
    msg = _broadcast_with_status(BroadcastStatus.DISPATCHING)
    partial = [ChannelDeliveryResult.success("-1001234567890")]

    msg.abort_dispatch(partial)

    assert msg.status == BroadcastStatus.CANCELLED
    assert msg.delivery_results == partial
    assert msg.delivery_results is not partial


@pytest.mark.parametrize(
    "status",
    [s for s in BroadcastStatus if s != BroadcastStatus.DISPATCHING],
)
def test_abort_dispatch_rejects_broadcast_that_is_not_in_flight(status):
    msg = _broadcast_with_status(status)

    with pytest.raises(ValueError, match=r"^Only an in-flight broadcast can be aborted$"):
        msg.abort_dispatch([])

    assert msg.status == status


def test_broadcast_poll_fields_and_defaults():
    field_map = {f.name: f for f in dataclasses.fields(BroadcastPoll)}
    assert field_map["is_anonymous"].default is True
    assert field_map["allows_multiple_answers"].default is False
    assert field_map["poll_type"].default == PollType.REGULAR
    assert field_map["correct_option_id"].default is None
    assert field_map["explanation"].default is None
    assert field_map["is_closed"].default is False

    poll = BroadcastPoll(question="Qual sua cor favorita?", options=["Azul", "Vermelho"])
    assert poll.question == "Qual sua cor favorita?"
    assert poll.options == ["Azul", "Vermelho"]
    assert poll.is_anonymous is True
    assert poll.allows_multiple_answers is False
    assert poll.poll_type == PollType.REGULAR
    assert poll.correct_option_id is None
    assert poll.explanation is None
    assert poll.is_closed is False

    with pytest.raises(dataclasses.FrozenInstanceError):
        poll.question = "Outra"

    quiz = BroadcastPoll(
        question="Quanto é 2 + 2?",
        options=["3", "4"],
        poll_type=PollType.QUIZ,
        correct_option_id=1,
        explanation="2 + 2 = 4",
        is_closed=True,
    )
    assert quiz.poll_type == PollType.QUIZ
    assert quiz.correct_option_id == 1
    assert quiz.explanation == "2 + 2 = 4"
    assert quiz.is_closed is True


def test_broadcast_poll_validations_question():
    for empty_q in ("", "   ", None):
        with pytest.raises(ValueError, match=r"^question cannot be empty$"):
            BroadcastPoll(question=empty_q, options=["A", "B"])  # type: ignore

    with pytest.raises(ValueError, match=r"^question cannot exceed 300 characters$"):
        BroadcastPoll(question="A" * 301, options=["A", "B"])

    p_min = BroadcastPoll(question="A", options=["A", "B"])
    assert p_min.question == "A"
    p_max = BroadcastPoll(question="A" * 300, options=["A", "B"])
    assert len(p_max.question) == 300


def test_broadcast_poll_validations_options():
    with pytest.raises(ValueError, match=r"^poll must have at least 2 options$"):
        BroadcastPoll(question="Q?", options=[])

    with pytest.raises(ValueError, match=r"^poll must have at least 2 options$"):
        BroadcastPoll(question="Q?", options=["A"])

    with pytest.raises(ValueError, match=r"^poll cannot have more than 10 options$"):
        BroadcastPoll(question="Q?", options=[f"Opt {i}" for i in range(11)])

    for empty_opt in ("", "   ", None):
        with pytest.raises(ValueError, match=r"^poll option cannot be empty$"):
            BroadcastPoll(question="Q?", options=["Valid", empty_opt])  # type: ignore

    with pytest.raises(ValueError, match=r"^poll option cannot exceed 100 characters$"):
        BroadcastPoll(question="Q?", options=["Valid", "X" * 101])

    p2 = BroadcastPoll(question="Q?", options=["A", "B"])
    assert len(p2.options) == 2
    p10 = BroadcastPoll(question="Q?", options=["X" * 100 for _ in range(10)])
    assert len(p10.options) == 10
    assert len(p10.options[0]) == 100


def test_broadcast_poll_validations_quiz():
    opts = ["A", "B", "C"]
    with pytest.raises(ValueError, match=r"^quiz polls cannot allow multiple answers$"):
        BroadcastPoll(
            question="Q?",
            options=opts,
            poll_type=PollType.QUIZ,
            allows_multiple_answers=True,
            correct_option_id=0,
        )

    with pytest.raises(ValueError, match=r"^quiz polls require correct_option_id$"):
        BroadcastPoll(question="Q?", options=opts, poll_type=PollType.QUIZ, correct_option_id=None)

    with pytest.raises(ValueError, match=r"^correct_option_id must be an integer$"):
        BroadcastPoll(
            question="Q?",
            options=opts,
            poll_type=PollType.QUIZ,
            correct_option_id=True,  # bool subclass of int
        )

    with pytest.raises(ValueError, match=r"^correct_option_id must be an integer$"):
        BroadcastPoll(
            question="Q?",
            options=opts,
            poll_type=PollType.QUIZ,
            correct_option_id="0",  # type: ignore
        )

    with pytest.raises(ValueError, match=r"^correct_option_id is out of range$"):
        BroadcastPoll(question="Q?", options=opts, poll_type=PollType.QUIZ, correct_option_id=-1)

    with pytest.raises(ValueError, match=r"^correct_option_id is out of range$"):
        BroadcastPoll(question="Q?", options=opts, poll_type=PollType.QUIZ, correct_option_id=3)

    with pytest.raises(ValueError, match=r"^explanation cannot exceed 200 characters$"):
        BroadcastPoll(
            question="Q?",
            options=opts,
            poll_type=PollType.QUIZ,
            correct_option_id=0,
            explanation="E" * 201,
        )

    quiz_valid_0 = BroadcastPoll(
        question="Q?",
        options=opts,
        poll_type=PollType.QUIZ,
        correct_option_id=0,
        explanation="E" * 200,
    )
    assert quiz_valid_0.correct_option_id == 0
    assert len(quiz_valid_0.explanation) == 200

    quiz_valid_last = BroadcastPoll(
        question="Q?",
        options=opts,
        poll_type=PollType.QUIZ,
        correct_option_id=2,
    )
    assert quiz_valid_last.correct_option_id == 2


def test_broadcast_poll_validations_regular():
    opts = ["A", "B"]
    with pytest.raises(ValueError, match=r"^regular polls cannot have correct_option_id$"):
        BroadcastPoll(
            question="Q?",
            options=opts,
            poll_type=PollType.REGULAR,
            correct_option_id=0,
        )

    with pytest.raises(ValueError, match=r"^regular polls cannot have explanation$"):
        BroadcastPoll(
            question="Q?",
            options=opts,
            poll_type=PollType.REGULAR,
            explanation="Just note",
        )


def test_broadcast_message_with_poll():
    b_fields = {f.name: f for f in dataclasses.fields(BroadcastMessage)}
    assert b_fields["poll"].default is None

    poll = BroadcastPoll(question="Nova enquete?", options=["Sim", "Não"])
    msg = BroadcastMessage(
        id="b-poll-1",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        poll=poll,
    )
    assert msg.poll == poll
    assert msg.get_dispatch_strategy() == DispatchStrategy.POLL

    media = MediaAttachment(file_path="/tmp/pic.jpg", media_type=MediaType.PHOTO, file_size=100)
    with pytest.raises(ValueError, match=r"^Broadcast cannot have both media and poll$"):
        BroadcastMessage(
            id="b-poll-err",
            profile_id="p-1",
            target_channel_ids=["-1001234567890"],
            media=media,
            poll=poll,
        )

