"""Offline, non-AI operator copilot. No LLM APIs. Stdlib only."""

from .engine import CopilotResult, draft_replies, handle_claimed_chat
from .chathomebase import CLAIMED_URL
from .compliance import validate_draft, validate_incoming
from .ingest import ingest_history
from .logbook import Logbook

__all__ = [
    "CLAIMED_URL",
    "CopilotResult",
    "draft_replies",
    "handle_claimed_chat",
    "ingest_history",
    "validate_draft",
    "validate_incoming",
    "Logbook",
]
