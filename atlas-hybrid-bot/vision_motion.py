"""Non-LLM motion-based verb and hand-exchange enrichment (no API/LLM calls)."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from hybrid_annotator import (
    DEFAULT_MOTION_THRESHOLD,
    HandMotionProfile,
    _hand_activity_score,
    _infer_hand_roles,
    infer_clip_hand_roles,
)
from label_generator import split_actions

if TYPE_CHECKING:
    pass

_MOTION_ENRICH_ENABLED = os.getenv("VISION_MOTION_ENRICH", "true").strip().lower() not in {
    "0",
    "false",
    "no",
}

_MIN_WIPE_CONFIDENCE = 0.20
_MIN_EXCHANGE_CONFIDENCE = 0.12

_MISLABELLED_MANIPULATION = re.compile(
    r"^(reposition|adjust|organize|arrange|straighten|move)\s+",
    re.IGNORECASE,
)
_MANIPULATION_OBJECT = re.compile(
    r"^(?:reposition|adjust|organize|arrange|straighten|move)\s+"
    r"(.+?)\s+(?:on|in|into|at)\s+.+?\s+with\s+(left hand|right hand)\s*$",
    re.IGNORECASE,
)
_SIMPLE_OBJECT_HAND = re.compile(
    r"^(?:reposition|adjust|organize|arrange|straighten|move)\s+"
    r"(\S+)\s+with\s+(left hand|right hand)\s*$",
    re.IGNORECASE,
)
_DRAFT_HAND = re.compile(r"\bwith\s+(left hand|right hand)\b", re.IGNORECASE)
_WIPE_LABEL = re.compile(r"\b(?:wipe|scrub|clean|wash|dry|polish|rub)\b", re.IGNORECASE)


def _other_hand(hand: str) -> str:
    return "left hand" if hand == "right hand" else "right hand"


def extract_manipulation_object(label: str) -> str | None:
    """Parse object noun from reposition/adjust-style single-clause labels."""
    if not label:
        return None
    text = label.strip()
    match = _MANIPULATION_OBJECT.match(text)
    if match:
        return match.group(1).strip()
    match = _SIMPLE_OBJECT_HAND.match(text)
    if match:
        return match.group(1).strip()
    return None


def _draft_work_hand(label: str) -> str | None:
    match = _DRAFT_HAND.search(label or "")
    return match.group(1).lower() if match else None


def infer_segment_work_hands(
    motion_profiles: list[HandMotionProfile | None],
    *,
    threshold: float = DEFAULT_MOTION_THRESHOLD,
) -> list[str | None]:
    """Per-segment active (tool/wipe) hand from MediaPipe motion."""
    hands: list[str | None] = []
    for motion in motion_profiles:
        if motion is None or motion.frames_analyzed < 3:
            hands.append(None)
            continue
        work, _stab, conf = _infer_hand_roles(
            motion.peak_left,
            motion.peak_right,
            motion.angular_left,
            motion.angular_right,
            threshold,
        )
        if work and conf >= _MIN_EXCHANGE_CONFIDENCE:
            hands.append(work)
            continue
        if motion.peak_left >= motion.peak_right * 1.25 and motion.peak_left >= threshold:
            hands.append("left hand")
        elif motion.peak_right >= motion.peak_left * 1.25 and motion.peak_right >= threshold:
            hands.append("right hand")
        elif motion.v_left >= motion.v_right * 1.3 and motion.v_left >= threshold:
            hands.append("left hand")
        elif motion.v_right >= motion.v_left * 1.3 and motion.v_right >= threshold:
            hands.append("right hand")
        else:
            hands.append(None)
    return hands


def _fill_work_hands(
    work_hands: list[str | None],
    labels: list[str],
) -> list[str | None]:
    """Fill unknown segment hands from draft tags or nearest neighbor."""
    filled = list(work_hands)
    for index, label in enumerate(labels):
        if filled[index] is None:
            filled[index] = _draft_work_hand(label or "")
    for index in range(len(filled)):
        if filled[index] is None and index > 0:
            filled[index] = filled[index - 1]
    for index in range(len(filled) - 1, -1, -1):
        if filled[index] is None and index + 1 < len(filled):
            filled[index] = filled[index + 1]
    return filled


def motion_indicates_wiping(
    motion_profiles: list[HandMotionProfile | None],
    *,
    threshold: float = DEFAULT_MOTION_THRESHOLD,
) -> tuple[bool, str | None, str | None, float]:
    """
    True when wrist motion looks like bimanual wiping/scrubbing rather than
    a one-shot reposition.
    """
    work, stab, conf = infer_clip_hand_roles(motion_profiles, threshold)
    if work and stab and conf >= _MIN_WIPE_CONFIDENCE:
        return True, work, stab, conf

    min_act = threshold * 1.8
    for motion in motion_profiles:
        if motion is None or motion.frames_analyzed < 3:
            continue
        if not (motion.start_left_contact and motion.start_right_contact):
            continue
        act_left = _hand_activity_score(motion.peak_left, motion.angular_left)
        act_right = _hand_activity_score(motion.peak_right, motion.angular_right)
        if max(act_left, act_right) >= min_act and min(act_left, act_right) > 0:
            ratio = max(act_left, act_right) / min(act_left, act_right)
            if ratio >= 1.35:
                if act_left >= act_right:
                    return True, "left hand", "right hand", min(1.0, (ratio - 1) / ratio)
                return True, "right hand", "left hand", min(1.0, (ratio - 1) / ratio)
    return False, None, None, 0.0


def _find_hand_exchange_index(work_hands: list[str | None]) -> int | None:
    """First segment index where the active tool hand changes."""
    for index in range(1, len(work_hands)):
        prev, curr = work_hands[index - 1], work_hands[index]
        if prev and curr and prev != curr:
            return index
    return None


def build_bimanual_wipe_label(obj: str, work_hand: str, stabilize_hand: str) -> str:
    return f"hold {obj} with {stabilize_hand}, wipe {obj} with cloth in {work_hand}"


def build_exchange_segment_label(
    obj: str,
    from_hand: str,
    to_hand: str,
) -> str:
    stabilize = _other_hand(from_hand)
    return (
        f"hold {obj} with {stabilize}, "
        f"pass {obj} from {from_hand} to {to_hand}, "
        f"wipe {obj} with cloth in {to_hand}"
    )


def _labels_need_motion_enrichment(labels: list[str]) -> bool:
    if not labels:
        return False
    if any(_WIPE_LABEL.search(lbl or "") for lbl in labels):
        return any(_MISLABELLED_MANIPULATION.search(lbl or "") for lbl in labels)
    return all(_MISLABELLED_MANIPULATION.search(lbl or "") for lbl in labels)


def apply_clip_motion_enrichment(
    segment_labels: list[str],
    motion_profiles: list[HandMotionProfile | None] | None,
) -> list[str]:
    """
    Upgrade mislabelled reposition/adjust drafts to wipe when motion shows
    repetitive tool-hand work, and inject pass clauses when the active hand
    switches mid-clip.
    """
    if not _MOTION_ENRICH_ENABLED or not segment_labels:
        return segment_labels
    profiles = motion_profiles or []
    if not _labels_need_motion_enrichment(segment_labels):
        return segment_labels

    is_wiping, clip_work, clip_stab, wipe_conf = motion_indicates_wiping(profiles)
    work_hands = _fill_work_hands(infer_segment_work_hands(profiles), segment_labels)
    exchange_idx = _find_hand_exchange_index(work_hands)

    if not is_wiping and exchange_idx is None:
        return segment_labels

    obj = extract_manipulation_object(segment_labels[0] or "")
    if not obj:
        for label in segment_labels:
            obj = extract_manipulation_object(label or "")
            if obj:
                break
    if not obj:
        return segment_labels

    updated: list[str] = []
    for index, label in enumerate(segment_labels):
        if exchange_idx is not None:
            if index < exchange_idx:
                work = work_hands[index] or work_hands[exchange_idx - 1] or "right hand"
                updated.append(build_bimanual_wipe_label(obj, work, _other_hand(work)))
            elif index == exchange_idx:
                from_hand = work_hands[exchange_idx - 1] or "right hand"
                to_hand = work_hands[exchange_idx] or _other_hand(from_hand)
                updated.append(build_exchange_segment_label(obj, from_hand, to_hand))
            else:
                work = work_hands[index] or work_hands[exchange_idx] or "left hand"
                updated.append(build_bimanual_wipe_label(obj, work, _other_hand(work)))
        elif clip_work and clip_stab:
            updated.append(build_bimanual_wipe_label(obj, clip_work, clip_stab))
        else:
            work = work_hands[index] or _draft_work_hand(label or "") or "right hand"
            updated.append(build_bimanual_wipe_label(obj, work, _other_hand(work)))

    if any(a.lower() != b.lower() for a, b in zip(updated, segment_labels)):
        print(
            f"[Hybrid]: Vision motion enrichment "
            f"(wipe_conf={wipe_conf:.2f}, exchange_seg={exchange_idx}, "
            f"obj={obj}): '{updated[0]}'"
        )
    return updated
