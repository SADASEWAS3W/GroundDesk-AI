"""Application-layer request and persistence contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SupportRequest:
    run_id: str
    message: str
    identifier_value: str
    channel: str
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.message.strip():
            raise ValueError("run_id and message must not be empty")
        if not self.identifier_value.strip():
            raise ValueError("identifier_value must not be empty")
        if self.channel not in {"web", "gmail", "whatsapp"}:
            raise ValueError("channel must be web, gmail, or whatsapp")

    @property
    def identifier_type(self) -> str:
        return "phone" if self.channel == "whatsapp" else "email"


@dataclass(frozen=True, slots=True)
class SupportBusinessContext:
    customer_id: str
    ticket_id: str
    conversation_id: str
    channel: str
