from typing import List
from src.application.errors import ProfileNotFoundError
from src.domain.broadcast.message_template import MessageTemplate
from src.domain.ports.message_template_repository import IMessageTemplateRepository
from src.domain.ports.profile_repository import IProfileRepository


class ListMessageTemplatesUseCase:
    def __init__(
        self,
        template_repo: IMessageTemplateRepository,
        profile_repo: IProfileRepository,
    ):
        self.template_repo = template_repo
        self.profile_repo = profile_repo

    async def execute(self, profile_id: str) -> List[MessageTemplate]:
        profile = await self.profile_repo.get_by_id(profile_id)
        if not profile:
            raise ProfileNotFoundError(profile_id)

        return await self.template_repo.list_by_profile(profile_id)
