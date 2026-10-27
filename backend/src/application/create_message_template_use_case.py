import uuid
from dataclasses import dataclass
from typing import Optional
from src.application.errors import ProfileNotFoundError
from src.domain.broadcast.message_template import MessageTemplate
from src.domain.ports.message_template_repository import IMessageTemplateRepository
from src.domain.ports.profile_repository import IProfileRepository


@dataclass(frozen=True)
class CreateMessageTemplateDTO:
    profile_id: str
    name: str
    text: str
    button_text: Optional[str] = None
    button_url: Optional[str] = None


class CreateMessageTemplateUseCase:
    def __init__(
        self,
        template_repo: IMessageTemplateRepository,
        profile_repo: IProfileRepository,
    ):
        self.template_repo = template_repo
        self.profile_repo = profile_repo

    async def execute(self, dto: CreateMessageTemplateDTO) -> MessageTemplate:
        profile = await self.profile_repo.get_by_id(dto.profile_id)
        if not profile:
            raise ProfileNotFoundError(dto.profile_id)

        template = MessageTemplate(
            id=str(uuid.uuid4()),
            profile_id=dto.profile_id,
            name=dto.name,
            text=dto.text,
            button_text=dto.button_text,
            button_url=dto.button_url,
        )
        await self.template_repo.save(template)
        return template
