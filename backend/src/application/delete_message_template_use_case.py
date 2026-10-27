from src.domain.ports.message_template_repository import IMessageTemplateRepository


class DeleteMessageTemplateUseCase:
    def __init__(self, template_repo: IMessageTemplateRepository):
        self.template_repo = template_repo

    async def execute(self, template_id: str) -> bool:
        return await self.template_repo.delete(template_id)
