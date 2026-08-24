"""Offline, non-AI operator copilot. No LLM APIs. Stdlib only."""

from .engine import CopilotResult, draft_replies
from .compliance import validate_draft, validate_incoming
from .logbook import Logbook

__all__ = [
    "CopilotResult",
    "draft_replies",
    "validate_draft",
    "validate_incoming",
    "Logbook",
]
