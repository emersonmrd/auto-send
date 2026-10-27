import pytest
from datetime import datetime, timezone
from src.domain.broadcast.message_template import MessageTemplate
from src.domain.broadcast.broadcast_message import InlineButton


def test_create_valid_message_template_without_button():
    import dataclasses

    fields = {f.name: f for f in dataclasses.fields(MessageTemplate)}
    assert fields["button_text"].default is None
    assert fields["button_url"].default is None

    template = MessageTemplate(
        id="tmpl-1",
        profile_id="profile-1",
        name="Aviso Geral",
        text="Olá assinantes, temos novidades!",
    )
    assert template.id == "tmpl-1"
    assert template.profile_id == "profile-1"
    assert template.name == "Aviso Geral"
    assert template.text == "Olá assinantes, temos novidades!"
    assert template.button_text is None
    assert template.button_url is None
    assert isinstance(template.created_at, datetime)
    assert isinstance(template.updated_at, datetime)
    assert template.to_inline_button() is None


def test_create_valid_message_template_with_button():
    template = MessageTemplate(
        id="tmpl-2",
        profile_id="profile-1",
        name="Promoção",
        text="Acesse nossa loja oficial com desconto:",
        button_text="Comprar Agora",
        button_url="https://loja.exemplo.com/promo",
    )
    assert template.button_text == "Comprar Agora"
    assert template.button_url == "https://loja.exemplo.com/promo"
    btn = template.to_inline_button()
    assert isinstance(btn, InlineButton)
    assert btn.text == "Comprar Agora"
    assert btn.url == "https://loja.exemplo.com/promo"


def test_template_name_cannot_be_empty_or_whitespace():
    with pytest.raises(ValueError, match=r"^Template name cannot be empty$"):
        MessageTemplate(id="1", profile_id="p1", name="", text="Valido")

    with pytest.raises(ValueError, match=r"^Template name cannot be empty$"):
        MessageTemplate(id="1", profile_id="p1", name="   ", text="Valido")

    with pytest.raises(ValueError, match=r"^Template name cannot be empty$"):
        MessageTemplate(id="1", profile_id="p1", name=None, text="Valido")  # type: ignore


def test_template_name_max_length_100():
    valid = MessageTemplate(id="1", profile_id="p1", name="a" * 100, text="Valido")
    assert len(valid.name) == 100

    with pytest.raises(ValueError, match=r"^Template name cannot exceed 100 characters$"):
        MessageTemplate(id="1", profile_id="p1", name="a" * 101, text="Valido")


def test_template_profile_id_cannot_be_empty():
    with pytest.raises(ValueError, match=r"^profile_id cannot be empty$"):
        MessageTemplate(id="1", profile_id="", name="Nome", text="Valido")

    with pytest.raises(ValueError, match=r"^profile_id cannot be empty$"):
        MessageTemplate(id="1", profile_id="   ", name="Nome", text="Valido")

    with pytest.raises(ValueError, match=r"^profile_id cannot be empty$"):
        MessageTemplate(id="1", profile_id=None, name="Nome", text="Valido")  # type: ignore


def test_template_text_cannot_be_empty_or_whitespace():
    with pytest.raises(ValueError, match=r"^Template text cannot be empty$"):
        MessageTemplate(id="1", profile_id="p1", name="Nome", text="")

    with pytest.raises(ValueError, match=r"^Template text cannot be empty$"):
        MessageTemplate(id="1", profile_id="p1", name="Nome", text="   ")

    with pytest.raises(ValueError, match=r"^Template text cannot be empty$"):
        MessageTemplate(id="1", profile_id="p1", name="Nome", text=None)  # type: ignore


def test_template_text_max_length_4096():
    valid = MessageTemplate(id="1", profile_id="p1", name="Nome", text="a" * 4096)
    assert len(valid.text) == 4096

    with pytest.raises(ValueError, match=r"^Template text cannot exceed 4096 characters$"):
        MessageTemplate(id="1", profile_id="p1", name="Nome", text="a" * 4097)


def test_template_button_requires_both_text_and_url():
    with pytest.raises(ValueError, match=r"^Both button_text and button_url must be provided together$"):
        MessageTemplate(
            id="1",
            profile_id="p1",
            name="Nome",
            text="Valido",
            button_text="Clique aqui",
            button_url=None,
        )

    with pytest.raises(ValueError, match=r"^Both button_text and button_url must be provided together$"):
        MessageTemplate(
            id="1",
            profile_id="p1",
            name="Nome",
            text="Valido",
            button_text=None,
            button_url="https://exemplo.com",
        )

    with pytest.raises(ValueError, match=r"^Both button_text and button_url must be provided together$"):
        MessageTemplate(
            id="1",
            profile_id="p1",
            name="Nome",
            text="Valido",
            button_text="   ",
            button_url="https://exemplo.com",
        )


def test_template_button_rejects_insecure_or_private_urls():
    with pytest.raises(ValueError, match="Only https:// allowed"):
        MessageTemplate(
            id="1",
            profile_id="p1",
            name="Nome",
            text="Valido",
            button_text="Botao",
            button_url="http://exemplo.com",
        )

    with pytest.raises(ValueError, match="Private network prohibited"):
        MessageTemplate(
            id="1",
            profile_id="p1",
            name="Nome",
            text="Valido",
            button_text="Botao",
            button_url="https://localhost:8000",
        )


def test_to_inline_button_with_partial_state():
    template = MessageTemplate(id="1", profile_id="p1", name="N", text="T")
    assert template.to_inline_button() is None

    # Se um dos campos for None, to_inline_button retorna None
    template.button_text = "Texto"
    template.button_url = None
    assert template.to_inline_button() is None

    template.button_text = None
    template.button_url = "https://exemplo.com"
    assert template.to_inline_button() is None


def test_template_update_modifies_fields_and_validates():
    template = MessageTemplate(
        id="tmpl-1",
        profile_id="profile-1",
        name="Nome Inicial",
        text="Texto Inicial",
    )
    initial_updated_at = template.updated_at

    template.update(
        name="Nome Atualizado",
        text="Texto Atualizado",
        button_text="Link Novo",
        button_url="https://exemplo.com/novo",
    )

    assert template.name == "Nome Atualizado"
    assert template.text == "Texto Atualizado"
    assert template.button_text == "Link Novo"
    assert template.button_url == "https://exemplo.com/novo"
    assert template.updated_at >= initial_updated_at

    # Update falha se dados forem invalidos
    with pytest.raises(ValueError, match=r"^Template name cannot be empty$"):
        template.update(name="", text="Texto")
