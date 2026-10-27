from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.domain.broadcast.broadcast_message import (
    InlineButton,
)


@dataclass
class MessageTemplate:
    id: str
    profile_id: str
    name: str
    text: str
    button_text: Optional[str] = None
    button_url: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise ValueError("Template name cannot be empty")
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Template name cannot be empty")
        if len(self.name) > 100:
            raise ValueError("Template name cannot exceed 100 characters")

        if not isinstance(self.profile_id, str):
            raise ValueError("profile_id cannot be empty")
        self.profile_id = self.profile_id.strip()
        if not self.profile_id:
            raise ValueError("profile_id cannot be empty")

        if not isinstance(self.text, str):
            raise ValueError("Template text cannot be empty")
        self.text = self.text.strip()
        if not self.text:
            raise ValueError("Template text cannot be empty")
        if len(self.text) > 4096:
            raise ValueError("Template text cannot exceed 4096 characters")

        raw_btn_text = self.button_text.strip() if isinstance(self.button_text, str) else None
        raw_btn_url = self.button_url.strip() if isinstance(self.button_url, str) else None

        has_text = bool(raw_btn_text)
        has_url = bool(raw_btn_url)

        if has_text != has_url:
            raise ValueError("Both button_text and button_url must be provided together")

        if has_text:
            # Como has_text == has_url, ambos são verdadeiros aqui
            assert raw_btn_text is not None and raw_btn_url is not None  # pragma: no mutate
            btn = InlineButton(text=raw_btn_text, url=raw_btn_url)
            self.button_text = btn.text
            self.button_url = btn.url
        else:
            self.button_text = None
            self.button_url = None

    def to_inline_button(self) -> Optional[InlineButton]:
        if self.button_text is None:
            return None
        if self.button_url is None:
            return None
        return InlineButton(text=self.button_text, url=self.button_url)

    def update(
        self,
        name: str,
        text: str,
        button_text: Optional[str] = None,
        button_url: Optional[str] = None,
    ) -> None:
        self.name = name
        self.text = text
        self.button_text = button_text
        self.button_url = button_url
        self.__post_init__()
        self.updated_at = datetime.now(timezone.utc)
