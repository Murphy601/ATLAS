"""Non-LLM vision hand corrections from MediaPipe wrist motion (no API/LLM calls)."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from label_generator import _leading_verb, split_actions

if TYPE_CHECKING:
    from hybrid_annotator import HandMotionProfile

_VISION_ENABLED = os.getenv("VISION_HAND_CORRECT", "true").strip().lower() not in {
    "0",
    "false",
    "no",
}

_HOLD_ROTATE_CLAUSE = re.compile(
    r"^(hold|rotate)\s+(.+?)\s+with\s+(left hand|right hand)\s*$",
    re.IGNORECASE,
)
_TOOL_WORK_CLAUSE = re.compile(
    r"^(wipe|sand|polish|clean|wash|dry|scrub|rub|buff|file|grind)\s+"
    r"(.+?)\s+with\s+(.+?)\s+in\s+(left hand|right hand)\s*$",
    re.IGNORECASE,
)
_SINGLE_TOOL_IN_HAND = re.compile(
    r"^(trim|cut|shear|clip|iron|mop|scrub|vacuum|sweep|sand|polish)\s+"
    r"(.+?)\s+with\s+(.+?)\s+in\s+(left hand|right hand)\s*$",
    re.IGNORECASE,
)
_SIMPLE_WITH_HAND = re.compile(
    r"\bwith\s+(left hand|right hand|both hands)\b",
    re.IGNORECASE,
)


def _set_with_hand(clause: str, hand: str) -> str:
    return _SIMPLE_WITH_HAND.sub(f"with {hand}", clause, count=1)


def _set_tool_in_hand(clause: str, hand: str) -> str:
    return re.sub(
        r"\bin\s+(left hand|right hand|both hands)\b",
        f"in {hand}",
        clause,
        count=1,
        flags=re.IGNORECASE,
    )


def apply_vision_hand_corrections(
    label: str,
    motion: HandMotionProfile | None,
) -> str:
    """
    Reassign hand tags using MediaPipe wrist activity (no LLM).

    - Bimanual continuous work: faster wrist -> tool clause, slower -> hold clause
    - Single tool-in-hand clause: faster wrist -> working hand
    """
    if not _VISION_ENABLED or not label or label == "No Action" or motion is None:
        return label
    if motion.frames_analyzed < 3:
        return label
    if not (motion.start_left_contact or motion.start_right_contact):
        return label

    work = motion.work_hand
    stab = motion.stabilize_hand
    if not work:
        return _correct_single_clause_hand(label, motion)

    clauses = split_actions(label)
    if len(clauses) != 2:
        return _correct_single_clause_hand(label, motion)

    first, second = clauses[0].strip(), clauses[1].strip()
    hold_match = _HOLD_ROTATE_CLAUSE.match(first)
    tool_match = _TOOL_WORK_CLAUSE.match(second)
    if hold_match and tool_match and stab:
        corrected = (
            f"{hold_match.group(1)} {hold_match.group(2)} with {stab}, "
            f"{tool_match.group(1)} {tool_match.group(2)} "
            f"with {tool_match.group(3)} in {work}"
        )
        if corrected.lower() != label.lower():
            print(
                f"[Hybrid]: Vision reassigned hands "
                f"(vL={motion.v_left:.3f} vR={motion.v_right:.3f} "
                f"aL={motion.angular_left:.3f} aR={motion.angular_right:.3f}): "
                f"'{corrected}'"
            )
        return corrected

    # Reversed clause order after reorder pass: tool first, hold second
    tool_first = _TOOL_WORK_CLAUSE.match(first)
    hold_second = _HOLD_ROTATE_CLAUSE.match(second)
    if tool_first and hold_second and stab:
        corrected = (
            f"{hold_second.group(1)} {hold_second.group(2)} with {stab}, "
            f"{tool_first.group(1)} {tool_first.group(2)} "
            f"with {tool_first.group(3)} in {work}"
        )
        if corrected.lower() != label.lower():
            print(
                f"[Hybrid]: Vision reassigned hands "
                f"(vL={motion.v_left:.3f} vR={motion.v_right:.3f}): "
                f"'{corrected}'"
            )
        return corrected

    return _correct_single_clause_hand(label, motion)


def _correct_single_clause_hand(label: str, motion: HandMotionProfile) -> str:
    """Single-clause tool or pick-up labels: assign the visually active hand."""
    work = motion.work_hand
    if not work:
        return label
    clauses = split_actions(label)
    if len(clauses) != 1:
        return label
    clause = clauses[0].strip()
    tool_match = _SINGLE_TOOL_IN_HAND.match(clause)
    if tool_match and tool_match.group(4).lower() != work:
        corrected = (
            f"{tool_match.group(1)} {tool_match.group(2)} "
            f"with {tool_match.group(3)} in {work}"
        )
        print(f"[Hybrid]: Vision set tool hand to {work}: '{corrected}'")
        return corrected
    verb = _leading_verb(clause)
    if verb in {"pick up", "pass"} and "both hands" not in clause.lower():
        current = re.search(r"\bwith\s+(left hand|right hand)\b", clause, re.I)
        if current and current.group(1).lower() != work:
            corrected = _set_with_hand(clause, work)
            print(f"[Hybrid]: Vision set {verb} hand to {work}: '{corrected}'")
            return corrected
    return label
