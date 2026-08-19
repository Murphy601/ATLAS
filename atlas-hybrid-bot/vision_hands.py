"""Non-LLM vision hand corrections from MediaPipe wrist motion (no API/LLM calls)."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from hybrid_annotator import infer_clip_hand_roles
from label_generator import _leading_verb, split_actions

if TYPE_CHECKING:
    from hybrid_annotator import HandMotionProfile

_VISION_ENABLED = os.getenv("VISION_HAND_CORRECT", "true").strip().lower() not in {
    "0",
    "false",
    "no",
}

# Minimum confidence from peak-velocity ratio before overriding draft hand tags.
_MIN_HAND_CONFIDENCE = 0.25

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
_BIMANUAL_TOOL_LABEL = re.compile(
    r"\b(?:wipe|sand|polish|clean|wash|scrub|rub|buff|file|grind)\b",
    re.IGNORECASE,
)


def _apply_bimanual_hands(label: str, work_hand: str, stabilize_hand: str) -> str:
    """Set hold/rotate clause to stabilize_hand and tool clause to work_hand."""
    if not label or label == "No Action":
        return label
    label = label.strip()
    clauses = split_actions(label)
    if len(clauses) != 2:
        return label

    first, second = clauses[0].strip(), clauses[1].strip()
    hold_match = _HOLD_ROTATE_CLAUSE.match(first)
    tool_match = _TOOL_WORK_CLAUSE.match(second)
    if hold_match and tool_match:
        return (
            f"{hold_match.group(1)} {hold_match.group(2)} with {stabilize_hand}, "
            f"{tool_match.group(1)} {tool_match.group(2)} "
            f"with {tool_match.group(3)} in {work_hand}"
        )

    tool_first = _TOOL_WORK_CLAUSE.match(first)
    hold_second = _HOLD_ROTATE_CLAUSE.match(second)
    if tool_first and hold_second:
        return (
            f"{hold_second.group(1)} {hold_second.group(2)} with {stabilize_hand}, "
            f"{tool_first.group(1)} {tool_first.group(2)} "
            f"with {tool_first.group(3)} in {work_hand}"
        )
    return label


def apply_clip_hand_consensus(
    segment_labels: list[str],
    motion_profiles: list[HandMotionProfile | None] | None,
) -> list[str]:
    """
    Lock work/stabilize hands for the entire clip using the strongest peak-velocity
    signal across all segments. Prevents segment 1 from swapping on noise while
    segments 2–4 keep the wrong draft.
    """
    if not _VISION_ENABLED or not segment_labels:
        return segment_labels
    if not any(_BIMANUAL_TOOL_LABEL.search(lbl or "") for lbl in segment_labels):
        return segment_labels

    work, stab, confidence = infer_clip_hand_roles(motion_profiles or [])
    if not work or not stab or confidence < _MIN_HAND_CONFIDENCE:
        if _VISION_ENABLED and any(
            _BIMANUAL_TOOL_LABEL.search(lbl or "") for lbl in segment_labels
        ):
            sample = next(
                (m for m in (motion_profiles or []) if m and m.frames_analyzed >= 3),
                None,
            )
            if sample:
                print(
                    "[Hybrid]: Vision hand consensus skipped "
                    f"(confidence={confidence:.2f}, need>={_MIN_HAND_CONFIDENCE:.2f}, "
                    f"peakL={sample.peak_left:.3f} peakR={sample.peak_right:.3f}, "
                    f"angL={sample.angular_left:.3f} angR={sample.angular_right:.3f})"
                )
        return segment_labels

    updated: list[str] = []
    changed = False
    for label in segment_labels:
        corrected = _apply_bimanual_hands(label or "", work, stab)
        if corrected.lower() != (label or "").lower():
            changed = True
        updated.append(corrected)

    if changed:
        sample_motion = next(
            (m for m in (motion_profiles or []) if m and m.frames_analyzed >= 3),
            None,
        )
        peak_l = sample_motion.peak_left if sample_motion else 0.0
        peak_r = sample_motion.peak_right if sample_motion else 0.0
        print(
            f"[Hybrid]: Vision clip hand consensus "
            f"(work={work}, stabilize={stab}, confidence={confidence:.2f}, "
            f"peakL={peak_l:.3f} peakR={peak_r:.3f} "
            f"angL={sample_motion.angular_left if sample_motion else 0.0:.3f} "
            f"angR={sample_motion.angular_right if sample_motion else 0.0:.3f}): "
            f"'{updated[0]}'"
        )
    return updated


def apply_vision_hand_corrections(
    label: str,
    motion: HandMotionProfile | None,
) -> str:
    """
    Per-segment hand fix — only when this segment alone has high-confidence
    peak-velocity asymmetry. Clip-level consensus in apply_clip_hand_consensus
    is preferred for multi-segment tasks.
    """
    if not _VISION_ENABLED or not label or label == "No Action" or motion is None:
        return label
    if motion.frames_analyzed < 3:
        return label
    if motion.hand_confidence < _MIN_HAND_CONFIDENCE:
        return label
    if not motion.work_hand or not motion.stabilize_hand:
        return label

    if len(split_actions(label)) == 2 and _BIMANUAL_TOOL_LABEL.search(label):
        corrected = _apply_bimanual_hands(
            label, motion.work_hand, motion.stabilize_hand
        )
        if corrected.lower() != label.lower():
            print(
                f"[Hybrid]: Vision segment hand fix "
                f"(peakL={motion.peak_left:.3f} peakR={motion.peak_right:.3f}, "
                f"conf={motion.hand_confidence:.2f}): '{corrected}'"
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
            corrected = re.sub(
                r"\bwith\s+(left hand|right hand)\b",
                f"with {work}",
                clause,
                count=1,
                flags=re.IGNORECASE,
            )
            print(f"[Hybrid]: Vision set {verb} hand to {work}: '{corrected}'")
            return corrected
    return label
