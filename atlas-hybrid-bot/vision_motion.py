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
_MANIPULATION_ON_SURFACE = re.compile(
    r"^(?:reposition|adjust|organize|arrange|straighten|move)\s+"
    r"(.+?)\s+(?:on|in|into|at)\s+((?:[\w-]+\s+)*(?:"
    r"shelf|wardrobe|counter|table|desk|door|wall|refrigerator|cabinet|drawer|closet|"
    r"floor|ground|surface|rack"
    r"))\s+with\s+(left hand|right hand)\s*$",
    re.IGNORECASE,
)
_SIMPLE_OBJECT_HAND = re.compile(
    r"^(?:reposition|adjust|organize|arrange|straighten|move)\s+"
    r"(\S+)\s+with\s+(left hand|right hand)\s*$",
    re.IGNORECASE,
)
_DRAFT_HAND = re.compile(r"\bwith\s+(left hand|right hand)\b", re.IGNORECASE)
_WIPE_LABEL = re.compile(r"\b(?:wipe|scrub|clean|wash|dry|polish|rub)\b", re.IGNORECASE)

# Small items in a reposition draft are often misidentified; the surface is the wipe target.
_SURFACE_WIPE_ITEMS = frozenset(
    {
        "sock",
        "socks",
        "item",
        "items",
        "thing",
        "things",
        "object",
        "objects",
        "clothes",
        "clothing",
        "garment",
        "garments",
        "towel",
        "towels",
        "cloth",
        "package",
        "box",
        "container",
    }
)


def _other_hand(hand: str) -> str:
    return "left hand" if hand == "right hand" else "right hand"


def _normalize_surface(surface: str) -> str:
    text = " ".join(surface.lower().split())
    if text.startswith("refrigerator "):
        return text
    return text.split()[-1] if text else surface


def extract_wipe_target(label: str) -> tuple[str, str]:
    """
    Parse wipe target from reposition-style labels.

    Returns (noun, kind) where kind is 'surface' or 'object'.
    'reposition socks on shelf' → wipe the shelf, not the socks.
    """
    if not label:
        return "", "object"
    text = label.strip()
    match = _MANIPULATION_ON_SURFACE.match(text)
    if match:
        item = match.group(1).strip().lower()
        surface = _normalize_surface(match.group(2).strip())
        if item in _SURFACE_WIPE_ITEMS:
            return surface, "surface"
        return item, "object"
    match = _SIMPLE_OBJECT_HAND.match(text)
    if match:
        return match.group(1).strip(), "object"
    return "", "object"


def extract_manipulation_object(label: str) -> str | None:
    """Back-compat: returns wipe target noun regardless of kind."""
    target, _kind = extract_wipe_target(label)
    return target or None


def _draft_work_hand(label: str) -> str | None:
    match = _DRAFT_HAND.search(label or "")
    return match.group(1).lower() if match else None


def _both_hands_tracked_in_clip(
    motion_profiles: list[HandMotionProfile | None],
) -> bool:
    tracked = 0
    for motion in motion_profiles:
        if motion is None or motion.frames_analyzed < 3:
            continue
        if motion.start_left_contact:
            tracked |= 1
        if motion.start_right_contact:
            tracked |= 2
    return tracked == 3


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
        if not (motion.start_left_contact and motion.start_right_contact):
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


def _segment_shows_wipe_activity(
    motion: HandMotionProfile | None,
    *,
    threshold: float = DEFAULT_MOTION_THRESHOLD,
) -> bool:
    """True when one wrist shows repetitive wipe/scrub motion."""
    if motion is None or motion.frames_analyzed < 3:
        return False
    min_act = threshold * 1.8
    act_left = _hand_activity_score(motion.peak_left, motion.angular_left)
    act_right = _hand_activity_score(motion.peak_right, motion.angular_right)
    return max(act_left, act_right) >= min_act


def _clip_shows_wipe_activity(
    motion_profiles: list[HandMotionProfile | None],
    *,
    threshold: float = DEFAULT_MOTION_THRESHOLD,
) -> bool:
    is_wiping, _, _, _ = motion_indicates_wiping(motion_profiles, threshold=threshold)
    if is_wiping:
        return True
    return any(
        _segment_shows_wipe_activity(motion, threshold=threshold)
        for motion in motion_profiles
    )


def _clip_draft_hand(labels: list[str]) -> str:
    for label in labels:
        hand = _draft_work_hand(label or "")
        if hand:
            return hand
    return "right hand"


def _resolve_surface_wipe_hand(
    motion_profiles: list[HandMotionProfile | None],
    clip_draft_hand: str,
    *,
    threshold: float = DEFAULT_MOTION_THRESHOLD,
) -> tuple[str, str]:
    """
    Pick the wiping hand for surface labels.

    When MediaPipe only ever tracks one wrist, trust that side over the AI draft
    (draft often says the wrong hand on ego clips). When both wrists appear,
    keep the draft hand to avoid seek-fallback flip-flops.
    """
    saw_left = False
    saw_right = False
    for motion in motion_profiles:
        if motion is None or motion.frames_analyzed < 3:
            continue
        if motion.start_left_contact:
            saw_left = True
        if motion.start_right_contact:
            saw_right = True
    if saw_left and not saw_right:
        return "left hand", "motion"
    if saw_right and not saw_left:
        return "right hand", "motion"
    return clip_draft_hand, "draft"


def _segments_with_both_hands(
    motion_profiles: list[HandMotionProfile | None],
) -> int:
    return sum(
        1
        for motion in motion_profiles
        if motion
        and motion.frames_analyzed >= 3
        and motion.start_left_contact
        and motion.start_right_contact
    )


def _find_hand_exchange_index(
    work_hands: list[str | None],
    motion_profiles: list[HandMotionProfile | None],
) -> int | None:
    """
    First segment where the tool hand changes with stable tracking.

    Surface wipes ignore exchange at segment 1 (seek noise) and require both
    wrists visible in at least two segments.
    """
    if not _both_hands_tracked_in_clip(motion_profiles):
        return None
    if _segments_with_both_hands(motion_profiles) < 2:
        return None

    for index in range(2, len(work_hands)):
        prev, curr = work_hands[index - 1], work_hands[index]
        if not prev or not curr or prev == curr:
            continue
        before = [hand for hand in work_hands[:index] if hand]
        after = [hand for hand in work_hands[index:] if hand]
        if before.count(prev) < 1 or after.count(curr) < 1:
            continue
        return index
    return None


def build_object_wipe_label(obj: str, work_hand: str, stabilize_hand: str) -> str:
    return f"hold {obj} with {stabilize_hand}, wipe {obj} with cloth in {work_hand}"


def build_surface_wipe_label(surface: str, work_hand: str) -> str:
    return f"wipe {surface} with cloth in {work_hand}"


def build_cloth_exchange_label(surface: str, from_hand: str, to_hand: str) -> str:
    return (
        f"pass cloth from {from_hand} to {to_hand}, "
        f"wipe {surface} with cloth in {to_hand}"
    )


def build_object_cloth_exchange_label(
    obj: str,
    from_hand: str,
    to_hand: str,
) -> str:
    stabilize = _other_hand(from_hand)
    return (
        f"hold {obj} with {stabilize}, "
        f"pass cloth from {from_hand} to {to_hand}, "
        f"wipe {obj} with cloth in {to_hand}"
    )


def build_bimanual_wipe_label(obj: str, work_hand: str, stabilize_hand: str) -> str:
    return build_object_wipe_label(obj, work_hand, stabilize_hand)


def build_exchange_segment_label(
    obj: str,
    from_hand: str,
    to_hand: str,
    *,
    target_kind: str = "object",
) -> str:
    if target_kind == "surface":
        return build_cloth_exchange_label(obj, from_hand, to_hand)
    return build_object_cloth_exchange_label(obj, from_hand, to_hand)


def _labels_need_motion_enrichment(labels: list[str]) -> bool:
    if not labels:
        return False
    if any(_WIPE_LABEL.search(lbl or "") for lbl in labels):
        return any(_MISLABELLED_MANIPULATION.search(lbl or "") for lbl in labels)
    return all(_MISLABELLED_MANIPULATION.search(lbl or "") for lbl in labels)


def _resolve_wipe_target(labels: list[str]) -> tuple[str, str]:
    for label in labels:
        target, kind = extract_wipe_target(label or "")
        if target:
            return target, kind
    return "", "object"


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

    target, target_kind = _resolve_wipe_target(segment_labels)
    if not target:
        return segment_labels

    is_wiping, clip_work, clip_stab, wipe_conf = motion_indicates_wiping(profiles)
    work_hands = _fill_work_hands(infer_segment_work_hands(profiles), segment_labels)
    exchange_idx = _find_hand_exchange_index(work_hands, profiles)
    has_wipe_motion = is_wiping or _clip_shows_wipe_activity(profiles)

    if not has_wipe_motion and exchange_idx is None:
        return segment_labels

    clip_draft_hand = _clip_draft_hand(segment_labels)

    # Surface wiping: one stable hand for the whole clip unless a late exchange.
    if target_kind == "surface" and exchange_idx is None:
        wipe_hand, hand_source = _resolve_surface_wipe_hand(profiles, clip_draft_hand)
        locked = build_surface_wipe_label(target, wipe_hand)
        if any((label or "").lower() != locked.lower() for label in segment_labels):
            hand_note = (
                f"{wipe_hand} ({hand_source}, draft={clip_draft_hand})"
                if hand_source == "motion" and wipe_hand != clip_draft_hand
                else wipe_hand
            )
            print(
                f"[Hybrid]: Vision motion enrichment "
                f"(wipe_conf={wipe_conf:.2f}, exchange_seg=None, "
                f"target={target}[surface], hand={hand_note}): '{locked}'"
            )
        return [locked] * len(segment_labels)

    updated: list[str] = []
    for index, label in enumerate(segment_labels):
        draft_hand = _draft_work_hand(label or "") or clip_draft_hand

        if target_kind == "surface":
            if exchange_idx is not None:
                to_hand = _other_hand(clip_draft_hand)
                if index < exchange_idx:
                    updated.append(build_surface_wipe_label(target, clip_draft_hand))
                elif index == exchange_idx:
                    to_hand = work_hands[exchange_idx] or to_hand
                    updated.append(
                        build_cloth_exchange_label(target, clip_draft_hand, to_hand)
                    )
                else:
                    work = work_hands[index] or to_hand
                    updated.append(build_surface_wipe_label(target, work))
                continue
            work = clip_draft_hand
            updated.append(build_surface_wipe_label(target, work))
        elif exchange_idx is not None:
            if index < exchange_idx:
                work = work_hands[index] or work_hands[exchange_idx - 1] or draft_hand
                updated.append(
                    build_object_wipe_label(target, work, _other_hand(work))
                )
            elif index == exchange_idx:
                from_hand = work_hands[exchange_idx - 1] or draft_hand
                to_hand = work_hands[exchange_idx] or _other_hand(from_hand)
                updated.append(
                    build_object_cloth_exchange_label(target, from_hand, to_hand)
                )
            else:
                work = work_hands[index] or work_hands[exchange_idx] or draft_hand
                updated.append(
                    build_object_wipe_label(target, work, _other_hand(work))
                )
        elif clip_work and clip_stab:
            updated.append(build_object_wipe_label(target, clip_work, clip_stab))
        else:
            work = work_hands[index] or draft_hand
            updated.append(
                build_object_wipe_label(target, work, _other_hand(work))
            )

    if any(a.lower() != b.lower() for a, b in zip(updated, segment_labels)):
        print(
            f"[Hybrid]: Vision motion enrichment "
            f"(wipe_conf={wipe_conf:.2f}, exchange_seg={exchange_idx}, "
            f"target={target}[{target_kind}]): '{updated[0]}'"
        )
    return updated
