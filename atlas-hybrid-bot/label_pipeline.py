"""Hybrid label generation: MediaPipe hands + Atlas draft surgery + regex (no LLM)."""

from __future__ import annotations

from frame_sampling import analyze_segment_motion, prepare_segment_frames
from frame_utils import frames_from_base64_list
from hybrid_annotator import AtlasHybridPipeline
from label_generator import (
    GlobalVideoContext,
    analyze_global_video_context,
    apply_context_fixes,
    apply_state_continuity,
    apply_verb_state_from_frames,
    draft_object_phrases,
    enforce_segment_action_limit,
    lint_atlas_syntax,
    sanitize_label,
    usable_draft,
)


def build_draft_global_context(segment_drafts: list[str]) -> GlobalVideoContext:
    """Pass 1 without LLM — object glossary from Atlas row drafts only."""
    return analyze_global_video_context([], segment_drafts=segment_drafts)


def finalize_hybrid_label(
    label: str,
    draft_label: str | None = None,
    previous_label: str | None = None,
    duration_seconds: float | None = None,
    global_context: GlobalVideoContext | None = None,
    motion_profile=None,
) -> str:
    """Post-process hybrid output without draft noun lock (lexicon already applied)."""
    if not label or label == "No Action":
        return label
    updated = apply_state_continuity(label, previous_label)
    updated = apply_verb_state_from_frames(updated, motion_profile)
    if global_context and global_context.objects:
        from label_generator import FORBIDDEN_GENERIC_OBJECTS
        import re

        for phrase in global_context.objects:
            for forbidden in FORBIDDEN_GENERIC_OBJECTS:
                updated = re.sub(
                    rf"\b{re.escape(forbidden)}\b",
                    phrase,
                    updated,
                    count=1,
                    flags=re.IGNORECASE,
                )
    updated = lint_atlas_syntax(updated)
    updated = sanitize_label(updated)
    updated = apply_context_fixes(
        updated,
        draft_label,
        previous_label,
        duration_seconds=duration_seconds,
    )
    return enforce_segment_action_limit(updated, duration_seconds)


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
    global_context: GlobalVideoContext | None = None,
    segment_start_seconds: float | None = None,
) -> str:
    """Deterministic Atlas label from captured frames + AI draft (no vision LLM)."""
    draft_label = usable_draft(draft_label)
    previous_label = usable_draft(previous_label)
    _ = (next_label, frames_have_video)

    if not draft_label:
        return "No Action"

    start_seconds = segment_start_seconds
    if start_seconds is None and frame_timestamps:
        start_seconds = min(frame_timestamps)
    start_seconds = start_seconds or 0.0

    motion_profile = analyze_segment_motion(base64_frames, frame_timestamps)
    prepared_frames, _prepared_times = prepare_segment_frames(
        base64_frames,
        frame_timestamps,
        duration_seconds=duration_seconds,
        start_seconds=start_seconds,
        motion_profile=motion_profile,
    )
    frame_arrays = frames_from_base64_list(prepared_frames or base64_frames)
    end_sec = start_seconds + (duration_seconds or 3.0)

    objects = draft_object_phrases(draft_label)
    target_object = objects[0] if objects else None

    hybrid_label = pipeline.process_frame_batch(
        frame_arrays,
        start_sec=start_seconds,
        end_sec=end_sec,
        draft_label=draft_label,
        target_object=target_object,
    )

    return finalize_hybrid_label(
        hybrid_label,
        draft_label,
        previous_label,
        duration_seconds,
        global_context,
        motion_profile,
    )
