#!/usr/bin/env python3
"""Public entry point for the offline non-AI copilot.

This is the operator-facing script requested in the spec. It does not call any
LLM API. Drafts are assembled from local rules, then hard-filtered.
"""

from __future__ import annotations

from datetime import date

from offline_copilot.compliance import validate_draft
from offline_copilot.engine import draft_replies


def build_response_options(client_name: str, client_city: str, user_message: str) -> list[str]:
    result = draft_replies(
        client_name,
        client_city,
        user_message,
        client_id=client_name,
        remember=False,
        today=date(2026, 8, 24),
    )
    if result.blocked:
        raise RuntimeError(result.reason)
    return result.options


if __name__ == "__main__":
    print("=== NON-AI CHAT COPILOT READY ===")
    test_name = "Nthabiseng"
    test_city = "Atlanta"
    test_msg = "Hey! Where are you located? Are you watching any games today?"
    print(f"\n[Incoming User Message]: '{test_msg}'")
    print(f"[Client City]: {test_city}\n")
    drafts = build_response_options(test_name, test_city, test_msg)
    for idx, draft in enumerate(drafts, 1):
        is_valid, reason = validate_draft(
            draft,
            client_name=test_name,
            client_city=test_city,
            location_required=True,
        )
        print(f"Option {idx}: {draft}")
        print(f"  └─ Compliance Check: {'PASSED' if is_valid else 'FAILED (' + reason + ')'}\n")
