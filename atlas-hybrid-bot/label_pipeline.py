"""Minimalist Atlas label pipeline — preserve draft meaning, fix grammar, append hand tag."""

from __future__ import annotations

import re

from frame_utils import frames_from_base64_list
from hybrid_annotator import AtlasHybridPipeline, _hand_tag_from_draft
from label_generator import usable_draft

# Imperative grammar only — never change verb meaning (no pick up → hold).
_ING_TO_IMPERATIVE = (
    ("picking up", "pick up"),
    ("putting down", "put down"),
    ("holding", "hold"),
    ("scrubbing", "scrub"),
    ("wiping", "wipe"),
    ("washing", "wash"),
    ("placing", "place"),
    ("sweeping", "sweep"),
    ("digging", "dig"),
    ("passing", "pass"),
    ("tightening", "tighten"),
    ("trimming", "trim"),
    ("stirring", "stir"),
    ("mixing", "mix"),
    ("folding", "fold"),
    ("ironing", "iron"),
    ("pouring", "pour"),
    ("scooping", "scoop"),
    ("lifting", "lift"),
    ("grabbing", "grab"),
    ("moving", "move"),
    ("opening", "open"),
    ("closing", "close"),
    ("turning", "turn"),
    ("pushing", "push"),
    ("pulling", "pull"),
    ("pressing", "press"),
    ("squeezing", "squeeze"),
    ("kneading", "knead"),
    ("scrapping", "scrape"),
    ("scraping", "scrape"),
    ("raking", "rake"),
    ("mopping", "mop"),
    ("brushing", "brush"),
    ("sanding", "sand"),
    ("hammering", "hammer"),
    ("drilling", "drill"),
    ("cutting", "cut"),
    ("chopping", "chop"),
    ("peeling", "peel"),
    ("inserting", "insert"),
    ("removing", "remove"),
    ("emptying", "empty"),
    ("filling", "fill"),
    ("watering", "water"),
    ("spraying", "spray"),
    ("drying", "dry"),
    ("polishing", "polish"),
    ("aligning", "align"),
    ("rotating", "rotate"),
    ("twisting", "twist"),
    ("pinching", "pinch"),
    ("gripping", "grip"),
    ("carrying", "carry"),
    ("lowering", "lower"),
    ("raising", "raise"),
    ("stacking", "stack"),
    ("unfolding", "unfold"),
    ("folding", "fold"),
    ("working", "work"),
)

_HAND_TAG_PATTERN = re.compile(
    r"\s+(?:with|in)\s+(?:left|right|both)\s+hands?\b",
    re.IGNORECASE,
)


def minimal_atlas_cleaner(draft_text: str, mp_hand_tag: str = "with right hand") -> str:
    """
    Do-no-harm cleaner: keep draft nouns/verbs, fix -ing grammar, one clause only,
    strip old hand tags, append hand attribution once.
    """
    label = (draft_text or "").strip()
    if not label or label.casefold() == "no action":
        return label

    for src, dst in _ING_TO_IMPERATIVE:
        label = re.sub(rf"\b{re.escape(src)}\b", dst, label, flags=re.IGNORECASE)

    label = re.sub(r"\s+(and|then)\s+", ", ", label, flags=re.IGNORECASE)
    label = re.sub(r"\s+,\s+", ", ", label)
    label = " ".join(label.split())

    clauses = [part.strip() for part in label.split(",") if part.strip()]
    label = clauses[0] if clauses else label

    label = _HAND_TAG_PATTERN.sub("", label)
    label = " ".join(label.split()).strip(" ,")

    hand = mp_hand_tag.strip()
    if not hand.startswith("with "):
        hand = f"with {hand}"
    return f"{label} {hand}".strip()


def resolve_hand_tag(draft_label: str, mp_hand_tag: str) -> str:
    """Prefer explicit hand in the Atlas draft; MediaPipe is fallback only."""
    draft_hand = _hand_tag_from_draft(draft_label)
    if draft_hand:
        return draft_hand
    return mp_hand_tag or "with right hand"


def generate_label_hybrid(
    base64_frames: list[str],
    pipeline: AtlasHybridPipeline,
    *,
    previous_label: str | None = None,
    draft_label: str | None = None,
    duration_seconds: float | None = None,
    frame_timestamps: list[float] | None = None,
    frames_have_video: bool = False,
    next_label: str | None = None,
    global_context=None,
    segment_start_seconds: float | None = None,
) -> str:
    """Minimal label from Atlas draft + optional MediaPipe hand tag (no LLM)."""
    draft_label = usable_draft(draft_label)
    _ = (
        previous_label,
        next_label,
        duration_seconds,
        frame_timestamps,
        frames_have_video,
        global_context,
        segment_start_seconds,
    )

    if not draft_label:
        return "No Action"

    mp_hand = "with right hand"
    if base64_frames:
        frame_arrays = frames_from_base64_list(base64_frames)
        if frame_arrays:
            motion = pipeline.analyze_frame_motion_from_memory(
                frame_arrays,
                draft_label=draft_label,
            )
            mp_hand = motion.detected_hand

    hand_tag = resolve_hand_tag(draft_label, mp_hand)
    return minimal_atlas_cleaner(draft_label, hand_tag)


def build_draft_global_context(segment_drafts: list[str]):
    """No-op for minimalist mode — kept for API compatibility with main.py."""
    from label_generator import GlobalVideoContext

    return GlobalVideoContext(objects=tuple())
