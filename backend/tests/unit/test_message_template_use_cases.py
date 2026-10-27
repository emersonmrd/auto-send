import pytest
from src.application.errors import ProfileNotFoundError
from src.application.create_message_template_use_case import (
    CreateMessageTemplateDTO,
    CreateMessageTemplateUseCase,
)
from src.application.list_message_templates_use_case import ListMessageTemplatesUseCase
from src.application.delete_message_template_use_case import DeleteMessageTemplateUseCase
from src.domain.broadcast.message_template import MessageTemplate
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.infrastructure.in_memory_repositories import InMemoryProfileRepository
from src.infrastructure.in_memory_repositories import InMemoryMessageTemplateRepository


@pytest.fixture
def profile_repo():
    repo = InMemoryProfileRepository()
    return repo


@pytest.fixture
def template_repo():
    repo = InMemoryMessageTemplateRepository()
    return repo


@pytest.fixture
async def sample_profile(profile_repo):
    profile = Profile(
        id="profile-1",
        name="Canal de Teste",
        credentials=BotCredentials(token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef", bot_username="teste_bot"),
    )
    await profile_repo.save(profile)
    return profile


@pytest.mark.asyncio
async def test_create_template_success(profile_repo, template_repo, sample_profile):
    use_case = CreateMessageTemplateUseCase(
        template_repo=template_repo,
        profile_repo=profile_repo,
    )
    dto = CreateMessageTemplateDTO(
        profile_id="profile-1",
        name="Aviso Importante",
        text="Atenção a todos os membros: servidor em manutenção.",
        button_text="Mais Informações",
        button_url="https://exemplo.com/ajuda",
    )

    created = await use_case.execute(dto)
    assert created.id
    assert created.profile_id == "profile-1"
    assert created.name == "Aviso Importante"
    assert created.text == "Atenção a todos os membros: servidor em manutenção."
    assert created.button_text == "Mais Informações"
    assert created.button_url == "https://exemplo.com/ajuda"

    # Verifica persistência
    saved = await template_repo.get_by_id(created.id)
    assert saved is not None
    assert saved.name == "Aviso Importante"


@pytest.mark.asyncio
async def test_create_template_raises_when_profile_not_found(profile_repo, template_repo):
    use_case = CreateMessageTemplateUseCase(
        template_repo=template_repo,
        profile_repo=profile_repo,
    )
    dto = CreateMessageTemplateDTO(
        profile_id="non-existent-profile",
        name="Aviso",
        text="Texto",
    )

    with pytest.raises(ProfileNotFoundError):
        await use_case.execute(dto)


@pytest.mark.asyncio
async def test_list_templates_success(profile_repo, template_repo, sample_profile):
    template1 = MessageTemplate(
        id="tmpl-1",
        profile_id="profile-1",
        name="Modelo 1",
        text="Texto 1",
    )
    template2 = MessageTemplate(
        id="tmpl-2",
        profile_id="profile-1",
        name="Modelo 2",
        text="Texto 2",
    )
    await template_repo.save(template1)
    await template_repo.save(template2)

    use_case = ListMessageTemplatesUseCase(
        template_repo=template_repo,
        profile_repo=profile_repo,
    )
    templates = await use_case.execute("profile-1")
    assert len(templates) == 2
    ids = [t.id for t in templates]
    assert "tmpl-1" in ids
    assert "tmpl-2" in ids


@pytest.mark.asyncio
async def test_list_templates_raises_when_profile_not_found(profile_repo, template_repo):
    use_case = ListMessageTemplatesUseCase(
        template_repo=template_repo,
        profile_repo=profile_repo,
    )
    with pytest.raises(ProfileNotFoundError):
        await use_case.execute("unknown-profile")


@pytest.mark.asyncio
async def test_delete_template_success(template_repo):
    template = MessageTemplate(
        id="tmpl-del",
        profile_id="profile-1",
        name="Para Deletar",
        text="Texto",
    )
    await template_repo.save(template)

    use_case = DeleteMessageTemplateUseCase(template_repo=template_repo)
    result = await use_case.execute("tmpl-del")
    assert result is True

    # Confirmar que foi removido
    assert await template_repo.get_by_id("tmpl-del") is None

    # Tentar deletar novamente retorna False
    assert await use_case.execute("tmpl-del") is False
