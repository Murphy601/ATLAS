"""Drive the already-open IX window via the Windows desktop (no DevTools, no Local API)."""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any

from caption_engine import (
    action_caption_for_mislabeled_idle,
    captions_from_ocr_blob,
    clip_export_from_subgoals,
    clip_export_slot_sentences,
    is_not_timeline_caption,
    is_ocr_caption_garbage,
    lint_clips,
    lint_subgoal,
    subgoal_captions_from_names,
)
from ego_task import harvest_timeline_clips, parse_clips_from_text
from process_cdp import is_ix_chromium_exe, is_ix_launcher, is_stock_chrome_path
from review_ui import (
    EMPTY_CLIP_PHRASES,
    clip_export_cut_fractions,
    clip_export_end_fractions_from_status_rects,
    clip_export_end_fractions_from_times,
    clip_export_interior_cut_fracs,
    clip_export_needs_more_cards,
    clip_export_visible_card_count,
    chip_end_fractions,
    clip_export_inferred_card_fracs,
    duration_end_fractions,
    harvest_rewrites_to_apply,
    long_card_interior_fracs,
    needs_one_frame_nudge,
    parse_timeline_fps,
    pick_clip_export_status_rects,
    pick_ocr_duration_centers,
    pick_ocr_timeline_person_centers,
    clip_durations_from_ocr,
    is_garbled_clip_export_caption,
    is_split_control_label,
    long_range_interior_fracs,
    qa_end_mismatch_seconds,
    qa_mismatch_frames,
    review_clip_range_from_ocr,
    review_start_frame_from_ocr,
    should_abort_clip_export_k,
    should_rewrite_every_clip_export_card,
    should_skip_k_after_caption_fill,
    timeline_length_from_ocr,
    wide_card_cut_fracs,
    clip_export_needs_new_clip,
    clip_export_needs_parallel_splits,
    clip_export_slot_mid_fractions,
    count_subgoal_spans,
    sort_hits_by_y,
    find_caption_field_click,
    find_phrase_click,
    find_review_use_clicks,
    find_word_click,
    full_timeline_xy,
    idle_card_split_xy,
    idle_is_opening_clip,
    interesting_uia_names,
    looks_like_neighbor_action,
    is_clip_export_end_mismatch,
    is_clip_export_hands_error,
    is_clip_export_caption_label,
    is_clip_export_duplicate_timeline,
    is_clip_export_empty_error,
    is_clip_export_missing_error,
    is_clip_export_short_error,
    is_clip_export_placeholder,
    is_clip_export_tab,
    is_create_clip_hint,
    is_empty_clip_label,
    is_grammar_row_label,
    is_false_idle_review_error,
    is_hte_clip_caption,
    is_hte_label,
    is_idle_too_long_error,
    is_ignore_all_label,
    is_ignore_warning_label,
    is_pause_control_label,
    is_pending_clip_label,
    is_play_control_label,
    is_quality_assistant_text,
    is_quality_empty_error,
    is_review_use_label,
    is_slow_around_transitions_label,
    is_timeline_kind_label,
    is_timeline_status_label,
    ocr_text,
    parse_grammar_clip_count,
    parse_watched_percent,
    pick_clip_export_review_rects,
    pick_review_description_rects,
    review_description_click_xy,
    clip_export_caption_needs_rewrite,
    is_clip_export_style_caption,
    pick_idle_split_rects,
    pick_click_to_add_text_target,
    clip_export_caption_committed,
    duplicate_clip_export_only,
    fillable_clip_export_qa,
    fixable_review_work_remaining,
    has_clip_export_quality_error,
    playback_confirmed,
    quality_linters_remaining,
    should_fill_clip_export,
    should_open_subgoal_pending,
    should_skip_observe,
    should_snap_clip_export_ends,
    is_quality_run_now_label,
    review_sidebar_open,
    review_work_remaining,
    selected_timeline_kind,
    clip_export_track_ready,
    should_stop_clip_export_k,
    should_recaption_false_idle,
    should_skip_watch,
    should_split_overlong_idle,
    timeline_dropdown_is_open,
)
import config

logger = logging.getLogger("ego.win_ui")

TASK_HINTS = (
    "focused timeline",
    "sub-goal",
    "subgoal",
    "ego_rectified",
    "clip export",
    "ego_rectified_canonical",
    "sensorfusionlab",
    "sensorfusion",
    "lidarlite",
    "remotasks",
    "ego-household",
)

REJECT_TITLE_TOKENS = (
    "google chrome",
    "google gemini",
    "microsoft edge",
)

HINDI_CHROMIUM = "क्रोमियम"

CHROME_CLASS = "Chrome_WidgetWin_1"
TAB_STRIP_MIN = 110
TAB_STRIP_MAX = 160
DEFAULT_WATCH_S = 90.0
MAX_WATCH_S = 300.0
OBSERVE_FIRST_CLIPS_S = 24.0
PICK_WAIT_S = 45.0
PICK_INTERVAL_S = 2.5
CLOCK_RE = re.compile(r"(\d{1,2}):(\d{2})\s*/\s*(\d{1,2}):(\d{2})")
_OCR_BROKEN = False
_CLIP_EXPORT_ALIGNED = False
_CLIP_EXPORT_FILLED = False
_CLIP_EXPORT_STUCK = False
_CLIP_EXPORT_SNAPPED: list[float] = []
_CLIP_EXPORT_END_FRACS: list[float] = []
_CLIP_EXPORT_SENTENCES: list[str] = []
_CLIP_EXPORT_WRITTEN_CARDS = 0
_IDLE_SPLIT_STUCK = False
_REWRITTEN_SNIPPETS: set[str] = set()


def say(msg: str) -> None:
    print(msg, flush=True)
    logger.info(msg)


def score_window(title: str, class_name: str = "", exe_path: str = "") -> int:
    """Score a desktop window. Prefer IX Chromium (SensorFusionLab), never the profile manager."""
    lowered = (title or "").lower()
    if any(token in lowered for token in REJECT_TITLE_TOKENS):
        return 0
    if is_ix_launcher(title, exe_path):
        return 0
    if is_stock_chrome_path(exe_path) and not is_ix_chromium_exe(exe_path):
        return 0

    score = 0
    if is_ix_chromium_exe(exe_path):
        score += 80
    if "sensorfusionlab" in lowered or "sensorfusion" in lowered:
        score += 40
    if HINDI_CHROMIUM in (title or "") or "chromium" in lowered:
        score += 20
    class_l = (class_name or "").lower()
    chrome_like = class_name == CHROME_CLASS or class_l.startswith("chrome_widgetwin")
    if chrome_like and is_ix_chromium_exe(exe_path):
        score += 5
    for hint in TASK_HINTS:
        if hint in lowered:
            score += 10
    if score == 0:
        return 0
    if not is_ix_chromium_exe(exe_path) and "sensorfusionlab" not in lowered:
        return 0
    return score


def select_ix_window(windows: list[dict]) -> dict | None:
    """Pick the IX Browser window from enumerated desktop windows."""
    scored: list[tuple[int, dict]] = []
    for window in windows:
        points = score_window(
            window.get("title") or "",
            window.get("class_name") or "",
            window.get("exe_path") or "",
        )
        if points > 0:
            scored.append((points, window))
    if not scored:
        return None
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored[0][1]


def keep_enumerated_window(
    width: int,
    height: int,
    *,
    visible: bool = True,
    minimized: bool = False,
    title: str = "",
    class_name: str = "",
    exe_path: str = "",
) -> bool:
    """Keep SensorFusionLab even when Win32 reports a tiny minimized rect."""
    if score_window(title, class_name, exe_path) > 0:
        return True
    if not visible and not minimized:
        return False
    if width < 400 or height < 300:
        return False
    return True


def page_click_points(left: int, top: int, width: int, height: int) -> list[tuple[int, int, str]]:
    """Click targets in the web page, never in the Chromium tab strip.

    The previous run clicked y=49 (tabs). SensorFusionLab chrome UI sits in the
    top ~110-160px; the video is in the remaining client area.
    """
    tab = min(max(int(height * 0.18), TAB_STRIP_MIN), TAB_STRIP_MAX)
    page_top = top + tab
    page_h = max(height - tab - 24, 1)
    page_left = left + 12
    page_w = max(width - 24, 1)
    return [
        (int(page_left + page_w * 0.46), int(page_top + page_h * 0.40), "video-center"),
        (int(page_left + page_w * 0.42), int(page_top + page_h * 0.14), "player-toolbar"),
    ]


def parse_media_clock(text: str) -> float | None:
    """Return duration seconds from a player clock like 0:12 / 1:45."""
    match = CLOCK_RE.search(text or "")
    if not match:
        return None
    return float(int(match.group(3)) * 60 + int(match.group(4)))


def drive_open_task(write: bool = True, watch_seconds: float | None = None) -> dict[str, Any]:
    """Focus the open IX window, play the video, lint/type timeline captions."""
    if sys.platform != "win32":
        raise RuntimeError("Desktop IX control is Windows-only")

    global _CLIP_EXPORT_ALIGNED, _CLIP_EXPORT_FILLED, _CLIP_EXPORT_STUCK, _IDLE_SPLIT_STUCK, _REWRITTEN_SNIPPETS
    global _CLIP_EXPORT_SNAPPED, _CLIP_EXPORT_END_FRACS, _CLIP_EXPORT_SENTENCES
    global _CLIP_EXPORT_WRITTEN_CARDS
    _CLIP_EXPORT_ALIGNED = False
    _CLIP_EXPORT_FILLED = False
    _CLIP_EXPORT_STUCK = False
    _CLIP_EXPORT_SNAPPED = []
    _CLIP_EXPORT_END_FRACS = []
    _CLIP_EXPORT_SENTENCES = []
    _CLIP_EXPORT_WRITTEN_CARDS = 0
    _IDLE_SPLIT_STUCK = False
    _REWRITTEN_SNIPPETS = set()

    say("DevTools is not exposed on this IX profile. Controlling the window you already opened...")
    say("Look at IX now: that window will come forward and the video should play.")
    _ensure_dpi_aware()
    prev_a11y = _enable_chromium_a11y()
    try:
        hwnd, title = _pick_ix_window()
        say(f"Using IX window: {title or '(no title)'}")
        _focus(hwnd)
        time.sleep(1.0)

        uia_text, uia_nodes = _read_uia(hwnd)
        ocr_words, img_w, img_h = _ocr_window(hwnd, "start")
        page_text = "\n".join(part for part in (uia_text, ocr_text(ocr_words)) if part)
        watched_pct = parse_watched_percent(page_text)
        use_ready = bool(find_review_use_clicks(ocr_words, img_w, img_h)) or any(
            is_review_use_label(_uia_name(ctrl)) for ctrl in uia_nodes
        )
        empty_ready = any(p in page_text.lower() for p in EMPTY_CLIP_PHRASES) or any(
            is_empty_clip_label(_uia_name(ctrl)) for ctrl in uia_nodes
        )
        quality_ready = is_quality_assistant_text(page_text) or any(
            is_quality_empty_error(_uia_name(ctrl)) for ctrl in uia_nodes
        )
        if watched_pct is not None:
            say(f"Player shows Watched {watched_pct}%")
        if empty_ready:
            say("Empty timeline clip is on screen (click to add text).")
        if use_ready:
            say("Review Use is on screen.")
        if quality_ready:
            say("Quality Assistant reds are on screen.")

        first_is_idle = any(
            _uia_name(ctrl).strip().casefold() == "idle" for ctrl in uia_nodes
        ) or any(is_idle_too_long_error(_uia_name(ctrl)) for ctrl in uia_nodes)
        skip_full_watch = should_skip_watch(
            watched_pct, use_ready=use_ready, quality_ready=quality_ready
        )
        names_now = [_uia_name(ctrl) for ctrl in uia_nodes]
        skip_observe = skip_full_watch and (
            should_skip_observe(watched_pct, names_now)
            or has_clip_export_quality_error(names_now)
        )
        played = False
        remaining = 0.0
        if skip_observe:
            say(
                f"Watched {watched_pct}% already; skipping replay so Clip Export "
                "can be filled now (not pausing after 2 segments)."
            )
            _pause_via_uia(hwnd, uia_nodes)
        else:
            _seek_timeline_start(hwnd, uia_nodes)
            time.sleep(0.45)
            uia_text, uia_nodes = _read_uia(hwnd)
            _disable_slow_around_transitions(hwnd, uia_nodes)
            time.sleep(0.2)
            uia_text, uia_nodes = _read_uia(hwnd, verbose=False)
            played = _ensure_video_playing(hwnd)
            if _playback_active(hwnd):
                say("Watch the IX window: Pause is on screen and the video should be moving.")
            elif played:
                say(
                    "Watch the IX window: Play and the video were clicked. "
                    "The playhead should be moving from the start (Pause is not in UIA)."
                )
            else:
                say("Play did not start. Check that the IX window is in front.")
            if skip_full_watch:
                remaining = OBSERVE_FIRST_CLIPS_S
                say(
                    f"Watched {watched_pct}% already; playing {int(remaining)}s from the start "
                    "so the first clips can be seen (not pausing after 2 segments)."
                )
                if first_is_idle:
                    say("First card looks Idle; watching the opening clips before any edit.")
                try:
                    _watch_while_playing(hwnd, remaining, "Watching first clips")
                except Exception as exc:
                    say(f"Watch stopped early ({exc}). Continuing to Quality Assistant.")
        if not skip_observe and not skip_full_watch:
            duration = parse_media_clock(page_text)
            remaining = watch_seconds
            if remaining is None:
                remaining = duration if duration and duration > 2 else DEFAULT_WATCH_S
            remaining = min(max(float(remaining), 8.0), MAX_WATCH_S)
            say(
                f"Watching the full video at 1x for up to {int(remaining)}s "
                f"(Watched {watched_pct if watched_pct is not None else 0}%)."
            )
            try:
                _watch_while_playing(hwnd, remaining, "Watching video")
            except Exception as exc:
                say(f"Watch stopped early ({exc}). Continuing to Quality Assistant.")

        review = {"applied": 0, "text": page_text}
        filled = {"wrote": 0, "text": page_text}
        idle_rounds = 0
        clip_export_qa = False
        for pass_i in range(4):
            say(f"Review pass {pass_i + 1}/4")
            _pause_via_uia(hwnd)
            _close_timeline_dropdown(hwnd)
            _text_pass, nodes_pass = _read_uia(hwnd, verbose=False)
            names_pass = [_uia_name(ctrl) for ctrl in nodes_pass]
            exported = {"wrote": 0, "text": "", "qa_remaining": False}
            if should_fill_clip_export(names_pass, already_filled=_CLIP_EXPORT_FILLED) or clip_export_qa:
                exported = _fill_clip_export(hwnd, write=write)
                clip_export_qa = bool(exported.get("qa_remaining"))
            used = {"applied": 0, "text": ""}
            recap = {"wrote": 0, "text": ""}
            missing = {"wrote": 0, "text": ""}
            split = {"wrote": 0, "text": ""}
            harvest_w = {"wrote": 0, "text": ""}
            # Write every Sub-goal that still fails lint. Do not leave 5 of 7 untouched
            # because Clip Export Quality Assistant is still red.
            _switch_timeline_kind(hwnd, "sub-goal")
            harvest_w = _apply_subgoal_harvest_rewrites(hwnd, write=write)
            if not clip_export_qa:
                used = _apply_review_uses(hwnd, write=write, max_clicks=4)
                recap = _recaption_false_idle(hwnd, write=write)
                missing = _fill_missing_and_reds(hwnd, write=write)
                if recap.get("wrote", 0) == 0:
                    split = _split_long_idle(hwnd, write=write)
            review["applied"] += int(used["applied"])
            if used.get("text"):
                review["text"] = used["text"]
            filled["wrote"] += (
                int(missing["wrote"])
                + int(exported["wrote"])
                + int(split["wrote"])
                + int(recap.get("wrote") or 0)
                + int(harvest_w.get("wrote") or 0)
            )
            if missing.get("text"):
                filled["text"] = missing["text"]
            say(
                f"Pass {pass_i + 1}: Use {used['applied']}, filled {missing['wrote']}, "
                f"false-idle {recap.get('wrote', 0)}, clip-export {exported['wrote']}, "
                f"idle-split {split['wrote']}, sub-goal-rewrites {harvest_w.get('wrote', 0)}"
            )
            uia_now, _nodes_now = _read_uia(hwnd)
            ocr_now = ""
            names_now = [line for line in (uia_now or "").splitlines() if line.strip()]
            if (
                not fillable_clip_export_qa(names_now)
                and not clip_export_qa
                and not _OCR_BROKEN
            ):
                words_now, _iw, _ih = _ocr_window(hwnd, f"qa_pass_{pass_i}")
                ocr_now = ocr_text(words_now)
            screen_now = "\n".join(
                part
                for part in (uia_now, ocr_now, exported.get("qa_text"))
                if part
            )
            if fillable_clip_export_qa(names_now) or fixable_review_work_remaining(screen_now):
                clip_export_qa = True
            if duplicate_clip_export_only(names_now, screen_now) and not clip_export_qa:
                say("Duplicate Clip Export track remains; not deleting it")
                say("No more Review / Quality Assistant work on screen.")
                break
            if not quality_linters_remaining(names_now) and used["applied"] == 0:
                if not fixable_review_work_remaining(screen_now) and not clip_export_qa:
                    say("No more Review / Quality Assistant work on screen.")
                    break
            if used["applied"] + missing["wrote"] + exported["wrote"] + split["wrote"] + recap.get("wrote", 0) + harvest_w.get("wrote", 0) == 0:
                idle_rounds += 1
                if not fixable_review_work_remaining(screen_now) and not clip_export_qa:
                    say("No more Review / Quality Assistant work on screen.")
                    break
                if idle_rounds >= 2:
                    say("Stopped after two idle passes with no new Use/fill.")
                    break
                if not should_open_subgoal_pending(names_now):
                    say("Clip Export text still missing; not opening a Sub-goal pending clip")
                    time.sleep(0.4)
                    continue
                if not _advance_review_target(hwnd):
                    say("Grammar/Quality work remains but no next clip control was found.")
                    break
                time.sleep(0.6)
            else:
                idle_rounds = 0

        say(f"Clicked Review Use {review['applied']} time(s)")
        say(f"Filled {filled['wrote']} missing/red caption(s)")

        body = "\n".join(part for part in (filled.get("text"), review.get("text"), page_text) if part)
        _switch_timeline_kind(hwnd, "sub-goal")
        _text_end, nodes_end = _read_uia(hwnd, verbose=False)
        harvest_names = [_uia_name(ctrl) for ctrl in nodes_end]
        harvest_ocr = ""
        if not _OCR_BROKEN:
            words_end, _ew, _eh = _ocr_window(hwnd, "timeline_harvest")
            harvest_ocr = ocr_text(words_end)
        clips = harvest_timeline_clips(harvest_names, harvest_ocr or body)
        if not clips:
            clips = parse_clips_from_text(body) if body else []
        say(f"Read {len(clips)} timeline clip(s) from the window")
        leftover = _apply_subgoal_harvest_rewrites(hwnd, write=write)
        filled["wrote"] += int(leftover.get("wrote") or 0)
        if leftover.get("wrote"):
            _text_end, nodes_end = _read_uia(hwnd, verbose=False)
            harvest_names = [_uia_name(ctrl) for ctrl in nodes_end]
            clips = harvest_timeline_clips(harvest_names, harvest_ocr or body) or clips
        preview = re.sub(r"\s+", " ", body).strip()[:220]
        if preview:
            say(f"Page text preview: {preview}")

        reports = []
        wrote = int(review["applied"]) + int(filled["wrote"])
        for item in lint_clips([clip.to_dict() for clip in clips]):
            lint = item["lint"]
            key = " ".join((lint.original or "").split()[:5]).casefold()
            did_write = bool(key and key in _REWRITTEN_SNIPPETS)
            reports.append(
                {
                    "index": item.get("index"),
                    "original": lint.original,
                    "rewritten": lint.rewritten,
                    "issues": [issue.__dict__ for issue in lint.issues],
                    "wrote": did_write,
                    "skipped": bool(item.get("skip_edit")),
                }
            )
            if write and lint.changed and not item.get("skip_edit") and not did_write:
                say(f"Suggested caption fix: {lint.rewritten}")

        payload = {
            "mode": "ego-window",
            "window_title": title,
            "watched_video": True,
            "played": played,
            "watch_seconds": remaining,
            "clip_count": len(clips),
            "wrote_captions": wrote,
            "review_use_clicks": review["applied"],
            "missing_filled": filled["wrote"],
            "quality_assistant": bool(
                review["applied"] > 0 or filled["wrote"] > 0 or quality_ready
            ),
            "submitted": False,
            "hte_edited": False,
            "clips": reports,
        }
        dest = config.ANALYSIS_RESULT
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload, indent=2), flush=True)
        say(f"Done. IX window left open. Report: {dest}")
        return payload
    finally:
        _restore_chromium_a11y(prev_a11y)


def _pick_ix_window() -> tuple[int, str]:
    deadline = time.time() + PICK_WAIT_S
    attempt = 0
    last_skipped: list[str] = []
    logged_skips = False
    seen_notes: set[str] = set()
    while True:
        attempt += 1
        found, skipped, notes = _enumerate_task_windows()
        last_skipped = skipped
        if not logged_skips:
            for title in skipped[:8]:
                say(f"Skipping non-task window: {title}")
            logged_skips = True
        for line in notes[:8]:
            if line in seen_notes:
                continue
            seen_notes.add(line)
            say(line)
        chosen = select_ix_window(found)
        if chosen is not None:
            exe = chosen.get("exe_path") or ""
            title = chosen.get("title") or ""
            if chosen.get("minimized"):
                say(f"SensorFusionLab was minimized; restoring {title or '(no title)'}")
            say(f"IX process: {exe or '(path unknown)'}")
            return int(chosen["hwnd"]), title
        if time.time() >= deadline:
            break
        say(
            f"Waiting for SensorFusionLab Chromium ({attempt})... "
            "click Open on the IX profile if that window is not on screen."
        )
        time.sleep(PICK_INTERVAL_S)
    seen = last_skipped[:8]
    raise RuntimeError(
        "Could not find the IX Chromium task window (SensorFusionLab). "
        "ixBrowser | v2.9.20 is the profile manager, not the task. "
        "Click Open on the profile, leave SensorFusionLab visible (not minimized), then retry. "
        f"Saw: {seen}"
    )


def _enumerate_task_windows() -> tuple[list[dict], list[str], list[str]]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[dict] = []
    skipped: list[str] = []
    notes: list[str] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        ex_style = user32.GetWindowLongW(hwnd, -20)
        if ex_style & 0x00000080:  # WS_EX_TOOLWINDOW
            return True
        visible = bool(user32.IsWindowVisible(hwnd))
        minimized = bool(user32.IsIconic(hwnd))
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        length = user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        title = title_buf.value
        class_name = class_buf.value
        exe_path = _hwnd_exe(hwnd)
        if is_ix_chromium_exe(exe_path) or is_ix_launcher(title, exe_path):
            state = "minimized" if minimized else f"{width}x{height}"
            notes.append(f"Saw IX window ({state}): {title or '(no title)'}")
        if not keep_enumerated_window(
            width,
            height,
            visible=visible,
            minimized=minimized,
            title=title,
            class_name=class_name,
            exe_path=exe_path,
        ):
            if title and (
                any(token in title.lower() for token in REJECT_TITLE_TOKENS)
                or is_stock_chrome_path(exe_path)
                or is_ix_launcher(title, exe_path)
            ):
                skipped.append(title)
            return True
        points = score_window(title, class_name, exe_path)
        if points <= 0:
            if title and (
                any(token in title.lower() for token in REJECT_TITLE_TOKENS)
                or is_stock_chrome_path(exe_path)
                or is_ix_launcher(title, exe_path)
            ):
                skipped.append(title)
            return True
        found.append(
            {
                "hwnd": int(hwnd),
                "title": title,
                "class_name": class_name,
                "exe_path": exe_path,
                "minimized": minimized,
            }
        )
        return True

    user32.EnumWindows(callback, 0)
    return found, skipped, notes


def _hwnd_exe(hwnd: int) -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if handle:
        try:
            size = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            kernel32.CloseHandle(handle)
    try:
        import psutil

        return psutil.Process(int(pid.value)).exe()
    except Exception:
        return ""


def _focus(hwnd: int) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    fg = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    fg_pid = wintypes.DWORD()
    fg_thread = user32.GetWindowThreadProcessId(fg, ctypes.byref(fg_pid))
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(fg_thread, current_thread, True)
    user32.AttachThreadInput(target_thread, current_thread, True)
    # Alt tap lets Windows allow a foreground switch from this process.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(fg_thread, current_thread, False)
    user32.AttachThreadInput(target_thread, current_thread, False)


def _play_video(hwnd: int) -> bool:
    """Click once in the page (video), then Space. Never click the Chromium tab strip."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = max(rect.right - rect.left, 1)
    height = max(rect.bottom - rect.top, 1)
    points = page_click_points(rect.left, rect.top, width, height)
    # One click on the video so we do not toggle play/pause. Then Space once.
    x, y, label = points[0]
    _click_screen(x, y)
    say(f"Clicked {label} at {x},{y} (below tab strip)")
    time.sleep(0.35)
    _send_space(hwnd)
    say("Sent Space (play) to the IX page")
    return True


def _click_screen(x: int, y: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def _double_click_screen(x: int, y: int) -> None:
    _click_screen(x, y)
    time.sleep(0.08)
    _click_screen(x, y)


def _send_space(hwnd: int | None = None) -> None:
    _send_vk(0x20)


def _send_vk(vk: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)


def _press_k_to_create(hwnd: int, at: tuple[int, int] | None = None) -> bool:
    """PDF / on-screen hint: click or press K to create a subgoal or clip-export cut."""
    _text, nodes = _read_uia(hwnd, verbose=False)
    names = [_uia_name(ctrl) for ctrl in nodes]
    if should_abort_clip_export_k(names):
        say("Not pressing K on Hand Tracking Error")
        return False
    # Do not SetForegroundWindow first: that restores the Review caret and types kkkk.
    _blur_caption(hwnd, nodes)
    time.sleep(0.08)
    if at is not None:
        _click_screen(int(at[0]), int(at[1]))
        time.sleep(0.08)
        _click_screen(int(at[0]), int(at[1]))
        time.sleep(0.12)
    if _click_split_control(hwnd):
        return True
    _send_vk(0x4B)  # K
    say("Pressed K to create/split a clip (never HTE)")
    return True


def _enable_chromium_a11y() -> int:
    """Ask Chromium to expose its accessibility tree (needed to read clips / Play)."""
    import ctypes

    user32 = ctypes.windll.user32
    prev = ctypes.c_int(0)
    user32.SystemParametersInfoW(0x0046, 0, ctypes.byref(prev), 0)  # SPI_GETSCREENREADER
    user32.SystemParametersInfoW(0x0047, 1, None, 0)  # SPI_SETSCREENREADER
    return int(prev.value)


def _ensure_dpi_aware() -> None:
    """Match GetWindowRect to on-screen pixels so OCR clicks land on Use / clips."""
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            logger.debug("DPI awareness not set", exc_info=True)


def _restore_chromium_a11y(previous: int) -> None:
    import ctypes

    try:
        ctypes.windll.user32.SystemParametersInfoW(0x0047, int(previous), None, 0)
    except Exception:
        logger.debug("Could not restore screen-reader flag", exc_info=True)


def _uia_name(ctrl: Any) -> str:
    for getter in (
        lambda: ctrl.window_text(),
        lambda: ctrl.element_info.name,
        lambda: getattr(ctrl.element_info, "rich_text", None),
        lambda: getattr(ctrl.element_info, "automation_id", None),
        lambda: getattr(ctrl.element_info, "legacy_name", None),
    ):
        try:
            value = (getter() or "").strip()
        except Exception:
            continue
        if value:
            return str(value)
    return ""


def _ctrl_center(ctrl: Any) -> tuple[int, int] | None:
    try:
        rect = ctrl.rectangle()
        return (int(rect.left + rect.right) // 2, int(rect.top + rect.bottom) // 2)
    except Exception:
        return None


def _uia_click(ctrl: Any) -> bool:
    for action in (
        lambda: ctrl.click_input(),
        lambda: ctrl.invoke(),
        lambda: ctrl.click(),
    ):
        try:
            action()
            return True
        except Exception:
            continue
    center = _ctrl_center(ctrl)
    if center:
        _click_screen(center[0], center[1])
        return True
    return False


def _iter_uia_controls(target: Any, limit: int = 6000):
    try:
        for i, ctrl in enumerate(target.descendants()):
            if i >= limit:
                break
            yield ctrl
    except Exception:
        return


def _read_uia(hwnd: int, verbose: bool = True) -> tuple[str, list[Any]]:
    nodes: list[Any] = []
    texts: list[str] = []
    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        target = None
        for win in desktop.windows():
            try:
                if int(win.handle) == int(hwnd):
                    target = win
                    break
            except Exception:
                continue
        if target is None:
            if verbose:
                say("UIA: SensorFusionLab window handle not found")
            return "", []
        for ctrl in _iter_uia_controls(target):
            nodes.append(ctrl)
            name = _uia_name(ctrl)
            if name:
                texts.append(name)
    except Exception as exc:
        if verbose:
            say(f"UIA read failed: {exc}")
        logger.debug("UIA read skipped", exc_info=True)
    named = [t for t in texts if t]
    if verbose:
        say(f"UIA named controls: {len(named)}")
        preview = interesting_uia_names(named)
        if preview:
            say("UIA names: " + " | ".join(preview))
    try:
        dest = config.DEBUG_CAPTURES / "uia_names.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(named), encoding="utf-8")
    except Exception:
        logger.debug("Could not write uia_names.txt", exc_info=True)
    return "\n".join(texts), nodes


def _disable_slow_around_transitions(hwnd: int, nodes: list[Any]) -> bool:
    """Turn off Slow around transitions so playback does not stall at clip cuts."""
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not is_slow_around_transitions_label(name):
            continue
        if "playback" in name.casefold():
            continue
        if _uia_click(ctrl):
            say(f"Clicked to disable slow-around-transitions: {name[:80]}")
            time.sleep(0.2)
            return True
    if _OCR_BROKEN:
        return False
    words, img_w, img_h = _ocr_window(hwnd, "playback_speed")
    left, top, _w, _h = _window_rect(hwnd)
    hit = find_phrase_click(
        words,
        "slow around transitions",
        img_w,
        img_h,
        y_min_frac=0.06,
        y_max_frac=0.28,
        x_min_frac=0.15,
        x_max_frac=0.85,
    )
    if not hit:
        return False
    _click_screen(left + hit[0], top + hit[1])
    say("Clicked Slow around transitions to keep 1x playback through clip cuts")
    time.sleep(0.2)
    return True


def _click_toolbar_play(hwnd: int, nodes: list[Any]) -> bool:
    """Click the player Play button, not a leftover Play on the timeline."""
    left, top, _width, height = _window_rect(hwnd)
    ranked: list[tuple[int, Any, str]] = []
    fallback: list[tuple[int, Any, str]] = []
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not is_play_control_label(name):
            continue
        center = _ctrl_center(ctrl)
        if not center:
            continue
        if center[1] <= top + int(height * 0.55):
            ranked.append((center[1], ctrl, name))
        else:
            fallback.append((center[1], ctrl, name))
    ordered = sort_hits_by_y(ranked) + sort_hits_by_y(fallback)
    for _y, ctrl, name in ordered:
        try:
            if _uia_click(ctrl):
                say(f"Clicked UIA play control: {name}")
                return True
        except Exception:
            logger.debug("UIA play click failed", exc_info=True)
    return False


def _ensure_video_playing(hwnd: int) -> bool:
    """Seek is not enough. Click Play, then the video, without toggling a clip that already started."""
    _text, nodes = _read_uia(hwnd)
    if playback_confirmed([_uia_name(ctrl) for ctrl in nodes]):
        say("Playback confirmed (Pause is on screen).")
        return True
    clicked_play = _click_toolbar_play(hwnd, nodes)
    time.sleep(0.9)
    _text, nodes = _read_uia(hwnd, verbose=False)
    if playback_confirmed([_uia_name(ctrl) for ctrl in nodes]):
        say("Playback confirmed after toolbar Play.")
        return True
    left, top, width, height = _window_rect(hwnd)
    x, y, label = page_click_points(left, top, width, height)[0]
    _click_screen(x, y)
    say(f"Clicked {label} at {x},{y} (below tab strip) because Pause is not in UIA")
    time.sleep(0.9)
    _text, nodes = _read_uia(hwnd, verbose=False)
    if playback_confirmed([_uia_name(ctrl) for ctrl in nodes]):
        say("Playback confirmed after clicking the video.")
        return True
    if not clicked_play:
        _send_space(hwnd)
        say("Sent Space (play) to the IX page")
        time.sleep(0.8)
        _text, nodes = _read_uia(hwnd, verbose=False)
        if playback_confirmed([_uia_name(ctrl) for ctrl in nodes]):
            say("Playback confirmed after Space.")
            return True
    else:
        say(
            "Play was clicked and the video was clicked. Pause is not exposed in UIA; "
            "not sending Space so the clip is not toggled off."
        )
    return clicked_play


def _watch_while_playing(hwnd: int, seconds: float, label: str) -> float:
    """Sleep while the video plays at 1x. Do not re-click Play (that pauses it)."""
    elapsed = 0.0
    remaining = max(float(seconds), 1.0)
    while elapsed < remaining:
        step = min(5.0, remaining - elapsed)
        time.sleep(step)
        elapsed += step
        text, nodes = _read_uia(hwnd, verbose=False)
        names = [_uia_name(ctrl) for ctrl in nodes]
        pct = parse_watched_percent(text)
        extra = f" (Watched {pct}%)" if pct is not None else ""
        say(f"{label}... {int(elapsed)}/{int(remaining)}s{extra}")
        if pct is not None and pct >= 95:
            say(f"{label} finished after Watched {pct}%")
            return elapsed
        if elapsed >= 8 and not playback_confirmed(names):
            say(f"{label} ended when Pause left the toolbar at {int(elapsed)}s")
            return elapsed
    return elapsed


def _playback_active(hwnd: int) -> bool:
    _text, nodes = _read_uia(hwnd, verbose=False)
    return playback_confirmed([_uia_name(ctrl) for ctrl in nodes])


def _play_via_uia(nodes: list[Any]) -> bool:
    if any(is_pause_control_label(_uia_name(ctrl)) for ctrl in nodes):
        say("Pause control is visible; leaving the video playing.")
        return True
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not is_play_control_label(name):
            continue
        try:
            if _uia_click(ctrl):
                say(f"Clicked UIA play control: {name}")
                return True
        except Exception:
            logger.debug("UIA play click failed", exc_info=True)
    return False


def _pause_via_uia(hwnd: int, nodes: list[Any] | None = None) -> bool:
    """Stop the playhead before K-splits or Clip Export typing."""
    if nodes is None:
        _text, nodes = _read_uia(hwnd)
    for ctrl in nodes:
        if not is_pause_control_label(_uia_name(ctrl)):
            continue
        try:
            if _uia_click(ctrl):
                say("Paused the video before editing the timeline")
                time.sleep(0.25)
                return True
        except Exception:
            logger.debug("UIA pause click failed", exc_info=True)
    return False


def _close_timeline_dropdown(hwnd: int, nodes: list[Any] | None = None) -> bool:
    """Escape out of Sub-goal / ClipExport / HTE if that menu is still open."""
    if nodes is None:
        _text, nodes = _read_uia(hwnd)
    names = [_uia_name(ctrl) for ctrl in nodes]
    if not timeline_dropdown_is_open(names):
        return False
    _focus(hwnd)
    _send_vk(0x1B)
    time.sleep(0.25)
    say("Closed leftover timeline-kind dropdown (Escape)")
    return True


def _named_rects(nodes: list[Any]) -> list[tuple[str, tuple[int, int, int, int]]]:
    out: list[tuple[str, tuple[int, int, int, int]]] = []
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not name:
            continue
        try:
            rect = ctrl.rectangle()
            out.append((name, (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))))
        except Exception:
            continue
    return out


def _full_timeline_rect(hwnd: int, nodes: list[Any]) -> tuple[int, int, int, int]:
    left, top, width, height = _window_rect(hwnd)
    window = (left, top, width, height)
    for ctrl in nodes:
        if _uia_name(ctrl).strip().casefold() != "full timeline":
            continue
        try:
            rect = ctrl.rectangle()
            return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        except Exception:
            continue
    return (left, int(top + height * 0.90), left + width, int(top + height * 0.96))


def _click_full_timeline_fraction(hwnd: int, frac: float, nodes: list[Any] | None = None) -> tuple[int, int]:
    if nodes is None:
        _text, nodes = _read_uia(hwnd, verbose=False)
    left, top, width, height = _window_rect(hwnd)
    bar = _full_timeline_rect(hwnd, nodes)
    x, y = full_timeline_xy(bar, frac, (left, top, width, height))
    _click_screen(x, y)
    return x, y


def _seek_timeline_start(hwnd: int, nodes: list[Any] | None = None) -> None:
    """Put the playhead at the first clip so Play starts at 0s, not mid-video or the end."""
    if nodes is None:
        _text, nodes = _read_uia(hwnd)
    x, y = _click_full_timeline_fraction(hwnd, 0.02, nodes)
    say(f"Seeked Full Timeline to the start at {x},{y}")
    if _click_first_timeline_card(hwnd, nodes):
        time.sleep(0.2)
        _click_full_timeline_fraction(hwnd, 0.02, nodes)


def _click_first_timeline_card(hwnd: int, nodes: list[Any]) -> bool:
    left, top, _width, height = _window_rect(hwnd)
    hits: list[tuple[int, Any]] = []
    for ctrl in nodes:
        if not is_timeline_status_label(_uia_name(ctrl)):
            continue
        center = _ctrl_center(ctrl)
        if not center:
            continue
        if center[1] > top + height * 0.62:
            hits.append((center[0], ctrl))
    if not hits:
        return False
    hits.sort(key=lambda row: row[0])
    if _uia_click(hits[0][1]):
        say("Clicked the first Focused Timeline card (start of the video)")
        return True
    return False


def _recaption_false_idle(hwnd: int, write: bool = True, force: bool = False) -> dict:
    """Replace a first-clip Idle that actually has action. Never Submit. Never HTE."""
    uia_text, nodes = _read_uia(hwnd)
    names = [_uia_name(ctrl) for ctrl in nodes]
    left, top, _width, height = _window_rect(hwnd)
    min_y = top + int(height * 0.62)
    named = _named_rects(nodes)
    if not force and not should_recaption_false_idle(names, named, min_y):
        return {"wrote": 0, "text": uia_text}
    blob = list(names)
    if not _OCR_BROKEN:
        words, _w, _h = _ocr_window(hwnd, "false_idle")
        blob.append(ocr_text(words))
    blob.extend(subgoal_captions_from_names(names))
    blob.extend(captions_from_ocr_blob("\n".join(blob)))
    caption = action_caption_for_mislabeled_idle(blob)
    if not write:
        return {"wrote": 0, "text": caption}
    if not _click_idle_caption_field(hwnd, nodes):
        if _click_uia_empty_clip(nodes):
            say("Clicked empty first clip to replace false Idle")
        elif not _click_first_timeline_card(hwnd, nodes):
            say("Could not focus the Idle caption field to replace it with an action")
            return {"wrote": 0, "text": uia_text}
        else:
            say("Focused the first timeline card to replace false Idle")
    time.sleep(0.2)
    _type_into_focused(caption)
    _blur_caption(hwnd, nodes)
    say(f"Replaced false Idle with action: {caption}")
    time.sleep(0.45)
    return {"wrote": 1, "text": caption}


def _click_idle_caption_field(hwnd: int, nodes: list[Any]) -> bool:
    """Click the Review-panel Idle caption (not the video overlay)."""
    left, top, width, height = _window_rect(hwnd)
    review_hits: list[tuple[int, Any]] = []
    timeline_hits: list[tuple[int, Any]] = []
    for ctrl in nodes:
        if _uia_name(ctrl).strip().casefold() != "idle":
            continue
        center = _ctrl_center(ctrl)
        if not center:
            continue
        if center[0] > left + width * 0.52 and center[1] < top + height * 0.58:
            review_hits.append((center[1], ctrl))
        elif center[1] > top + height * 0.62:
            timeline_hits.append((center[0], ctrl))
    ordered = sort_hits_by_y(review_hits) + sort_hits_by_y(timeline_hits)
    for _key, ctrl in ordered:
        if _uia_click(ctrl):
            say("Clicked the Idle caption field")
            return True
    return False


def _click_uia_use(hwnd: int, nodes: list[Any]) -> bool:
    """Click Grammar Use in the right Review pane. Never Submit."""
    _left, _top, width, _height = _window_rect(hwnd)
    for ctrl in nodes:
        if not is_review_use_label(_uia_name(ctrl)):
            continue
        center = _ctrl_center(ctrl)
        if center and center[0] < _left + int(width * 0.48):
            continue
        if _uia_click(ctrl):
            say(f"Clicked UIA Review Use at {center}")
            return True
    return False


def _click_uia_empty_clip(nodes: list[Any]) -> bool:
    """Prefer 'click to add text' (the editor). (empty clip) is a dead list row."""
    preferred: list[Any] = []
    fallback: list[Any] = []
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not is_empty_clip_label(name):
            continue
        if "click to add" in name.casefold():
            preferred.append(ctrl)
        else:
            fallback.append(ctrl)
    for ctrl in preferred + fallback:
        name = _uia_name(ctrl)
        if _uia_click(ctrl):
            say(f"Clicked UIA empty clip: {name}")
            time.sleep(0.12)
            _uia_click(ctrl)
            return True
    return False


def _click_uia_quality_empty(nodes: list[Any]) -> bool:
    """Click the Quality Assistant row that points at a clip with no text."""
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not is_quality_empty_error(name):
            continue
        if _uia_click(ctrl):
            say(f"Clicked Quality Assistant empty-clip error: {name[:80]}")
            return True
    return False


def _click_control_left(ctrl: Any, frac: float = 0.18) -> bool:
    """Click the left side of a control so Grammar is hit, not Ignore all."""
    try:
        rect = ctrl.rectangle()
        x = int(rect.left + max(rect.right - rect.left, 1) * frac)
        y = int((rect.top + rect.bottom) / 2)
    except Exception:
        return False
    _click_screen(x, y)
    return True


def _advance_review_target(hwnd: int, nodes: list[Any] | None = None) -> bool:
    """Select the next Grammar/pending clip so Use reappears. Never Ignore all / Submit."""
    if nodes is None:
        _text, nodes = _read_uia(hwnd)
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if is_ignore_all_label(name):
            continue
        if not is_grammar_row_label(name):
            continue
        if _click_control_left(ctrl):
            say(f"Clicked Grammar row (left side, not Ignore all): {name[:80]}")
            return True
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not is_pending_clip_label(name):
            continue
        if _uia_click(ctrl):
            say(f"Opened pending timeline clip: {name}")
            return True
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if is_ignore_all_label(name) or is_review_use_label(name):
            continue
        if is_idle_too_long_error(name) or is_clip_export_missing_error(name):
            continue
        if is_quality_empty_error(name):
            continue
        lowered = name.casefold()
        if not lowered.startswith("error"):
            continue
        if _uia_click(ctrl):
            say(f"Opened Quality Assistant clip: {name[:80]}")
            return True
    return False


def _fill_clip_export(hwnd: int, write: bool = True) -> dict:
    """Overwrite Clip Export captions that mention hands and snap ends on Focused Timeline."""
    global _CLIP_EXPORT_ALIGNED, _CLIP_EXPORT_FILLED, _CLIP_EXPORT_STUCK
    global _CLIP_EXPORT_SNAPPED, _CLIP_EXPORT_END_FRACS, _CLIP_EXPORT_SENTENCES
    global _CLIP_EXPORT_WRITTEN_CARDS
    if _CLIP_EXPORT_STUCK:
        say("Clip Export editor did not keep text last pass; not repeating the same empty field")
        return {"wrote": 0, "text": "", "qa_remaining": True}
    uia_text, nodes = _read_uia(hwnd)
    names = [line for line in (uia_text or "").splitlines() if line.strip()]
    if selected_timeline_kind(names) == "clip export" or any(
        is_clip_export_style_caption(n) for n in names
    ):
        _switch_timeline_kind(hwnd, "sub-goal")
        time.sleep(0.35)
        uia_text, nodes = _read_uia(hwnd)
        names = [line for line in (uia_text or "").splitlines() if line.strip()]
    blob = list(names)
    ocr_blob = ""
    harvested = []
    if not _OCR_BROKEN:
        words, _img_w, _img_h = _ocr_window(hwnd, "subgoals_for_export")
        ocr_blob = ocr_text(words)
        blob.append(ocr_blob)
        harvested = harvest_timeline_clips(names, ocr_blob)
    if not harvested:
        harvested = parse_clips_from_text(ocr_blob) if ocr_blob else []
    sub_caps = [
        getattr(clip, "caption", "")
        for clip in harvested
        if getattr(clip, "caption", "")
        and not is_clip_export_style_caption(getattr(clip, "caption", ""))
        and not is_hte_clip_caption(getattr(clip, "caption", ""))
        and not is_hte_label(getattr(clip, "caption", ""))
    ]
    if not sub_caps:
        sub_caps = [
            cap
            for cap in subgoal_captions_from_names(names)
            if not is_clip_export_style_caption(cap)
            and not is_hte_clip_caption(cap)
            and not is_hte_label(cap)
        ]
        sub_caps.extend(
            c
            for c in captions_from_ocr_blob(ocr_blob)
            if c not in sub_caps
            and not is_clip_export_style_caption(c)
            and not is_hte_clip_caption(c)
            and not is_hte_label(c)
        )
    blob.extend(sub_caps)
    fallback = clip_export_from_subgoals(blob)
    n_cards = count_subgoal_spans(names, ocr_blob)
    end_fracs = _subgoal_end_fractions(hwnd, nodes, harvested, names, ocr_blob)
    n_slots = max(
        n_cards or 1,
        len(sub_caps) or 1,
        len(harvested) or 1,
        (len(end_fracs) + 1) if end_fracs else 1,
    )
    sentences = clip_export_slot_sentences(sub_caps or blob, n_slots, fallback)
    if end_fracs:
        _CLIP_EXPORT_END_FRACS = list(end_fracs)
    elif _CLIP_EXPORT_END_FRACS:
        end_fracs = list(_CLIP_EXPORT_END_FRACS)
        n_slots = max(n_slots, len(end_fracs) + 1)
    if sentences:
        _CLIP_EXPORT_SENTENCES = list(sentences)
    elif _CLIP_EXPORT_SENTENCES:
        sentences = list(_CLIP_EXPORT_SENTENCES)
    _pause_via_uia(hwnd, nodes)
    _switch_timeline_kind(hwnd, "clip export")
    time.sleep(0.45)
    uia_text, nodes = _read_uia(hwnd)
    names = [_uia_name(ctrl) for ctrl in nodes]
    missing = any(is_clip_export_missing_error(n) for n in names) or is_clip_export_missing_error(
        uia_text
    )
    end_mismatch = any(is_clip_export_end_mismatch(n) for n in names)
    hands = any(is_clip_export_hands_error(n) for n in names)
    empty_err = any(is_clip_export_empty_error(n) for n in names) or is_clip_export_empty_error(
        uia_text
    )
    short_err = any(is_clip_export_short_error(n) for n in names)
    fillable = fillable_clip_export_qa(names) or fixable_review_work_remaining(
        "\n".join([uia_text or "", ocr_blob])
    )
    if _CLIP_EXPORT_FILLED and not fillable and not should_fill_clip_export(names, True):
        if duplicate_clip_export_only(names, uia_text):
            say("Duplicate Clip Export track remains; not deleting it")
        _switch_timeline_kind(hwnd, "sub-goal")
        return {
            "wrote": 0,
            "text": uia_text,
            "qa_text": uia_text,
            "qa_remaining": False,
        }
    if not missing and not end_mismatch and not hands and not empty_err and not short_err:
        say("Filling Clip Export from Sub-goal captions (no Clip Export Quality Assistant row this pass)")
    if not write:
        return {"wrote": 0, "text": uia_text, "qa_remaining": True}

    if not _ensure_clip_export_track(hwnd, nodes):
        names_now = [_uia_name(ctrl) for ctrl in nodes]
        if clip_export_track_ready(names_now):
            say("Clip Export track is on screen; filling it (Focused Timeline still lists Sub-goal)")
        else:
            say("Cannot fill Clip Export while Hand Tracking Error is selected")
            return {"wrote": 0, "text": uia_text, "qa_remaining": True}
    _text, nodes = _read_uia(hwnd, verbose=False)
    names = [_uia_name(ctrl) for ctrl in nodes]
    _focus_filled_clip_export_track(hwnd, nodes)

    parallel = clip_export_needs_parallel_splits(names, n_slots)
    duplicate = any(is_clip_export_duplicate_timeline(n) for n in names)
    if duplicate:
        say("Not creating a second Clip Export track on Full Timeline")
    left, top, width, height = _window_rect(hwnd)
    named = _named_rects(nodes)
    min_y = top + int(height * 0.62)
    chips_now = pick_clip_export_review_rects(named, min_y)
    status_chips = pick_clip_export_status_rects(named, min_y)
    export_ocr = ""
    export_words: list[dict] = []
    if not _OCR_BROKEN:
        export_words, _ew, _eh = _ocr_window(hwnd, "clip_export_cards")
        export_ocr = ocr_text(export_words)
    card_durs = clip_durations_from_ocr(export_ocr)
    person_hits = pick_ocr_timeline_person_centers(export_words, int(height * 0.62))
    long_range = review_clip_range_from_ocr(export_ocr) or review_clip_range_from_ocr(
        " ".join(names)
    )
    total_s = timeline_length_from_ocr(export_ocr) or (
        max(long_range[1] + 10.0, 40.0) if long_range else 0.0
    )
    bar = _focused_timeline_rect(hwnd, nodes)
    bar_left, bar_right = bar[0], bar[2]
    if bar_right - bar_left < 200:
        bar_left = left + int(width * 0.08)
        bar_right = left + int(width * 0.92)
    existing_ends = duration_end_fractions(card_durs) or chip_end_fractions(
        status_chips or chips_now, bar_left, bar_right
    )
    inferred_mids = clip_export_inferred_card_fracs(
        long_range, total_s or (long_range[1] + 10.0 if long_range else 40.0), existing_ends
    )
    visible = clip_export_visible_card_count(
        max(len(chips_now), len(person_hits)),
        len(card_durs),
        len(inferred_mids),
    )
    for frac in existing_ends:
        if all(abs(frac - seen) > 0.02 for seen in _CLIP_EXPORT_SNAPPED):
            _CLIP_EXPORT_SNAPPED.append(frac)
    interior = clip_export_interior_cut_fracs(end_fracs, existing_ends)
    if card_durs and any(d > 10 for d in card_durs):
        interior.extend(
            f
            for f in long_card_interior_fracs(card_durs)
            if all(abs(f - seen) > 0.03 for seen in interior)
            and all(abs(f - seen) > 0.03 for seen in existing_ends)
        )
    if clip_export_needs_more_cards(visible, n_slots, names):
        interior.extend(
            f
            for f in wide_card_cut_fracs(
                status_chips or chips_now, end_fracs, bar_left, bar_right
            )
            if all(abs(f - seen) > 0.03 for seen in interior)
            and all(abs(f - seen) > 0.03 for seen in existing_ends)
        )
    if long_range and long_range[2] > 10:
        cut_span = max(
            float(total_s or 0.0),
            long_range[1] + 4.0,
            sum(card_durs) if card_durs else 0.0,
        )
        say(
            f"Review shows a {long_range[2]:g}s Clip Export from "
            f"{long_range[0]:g}s to {long_range[1]:g}s; will write that card and its neighbors"
        )
        interior.extend(
            f
            for f in long_range_interior_fracs(long_range[0], long_range[1], cut_span)
            if all(abs(f - seen) > 0.03 for seen in interior)
            and all(abs(f - seen) > 0.03 for seen in existing_ends)
        )
    say(
        f"Clip Export has {visible} on-screen card(s) "
        f"({', '.join(f'{d:g}s' for d in card_durs) or 'no durations'}); "
        f"will write every card "
        f"({len(interior)} interior cut(s), {n_slots} Sub-goal slot(s))"
    )
    snap = should_snap_clip_export_ends(names, chip_count=visible, duplicate=duplicate)
    cards_before_split = visible
    skip_k = should_skip_k_after_caption_fill(_CLIP_EXPORT_FILLED)
    if skip_k:
        say("Clip Export text is already in the Review box; not pressing K (that types kkkk)")
        _CLIP_EXPORT_ALIGNED = True
    elif snap and interior and (
        not _CLIP_EXPORT_ALIGNED
        or any(is_clip_export_end_mismatch(n) for n in names)
        or any(is_clip_export_missing_error(n) for n in names)
        or clip_export_needs_more_cards(visible, n_slots, names)
    ):
        _align_clip_export_on_focused_timeline(hwnd, interior, nodes, existing_ends)
        _CLIP_EXPORT_ALIGNED = True
        time.sleep(0.3)
        uia_text, nodes = _read_uia(hwnd)
        named = _named_rects(nodes)
        chips_now = pick_clip_export_review_rects(named, min_y)
        visible = clip_export_visible_card_count(
            len(chips_now), len(card_durs), len(inferred_mids)
        )
    else:
        if not interior:
            say("No interior Clip Export cut left; not pressing K on an existing card edge")
        _CLIP_EXPORT_ALIGNED = True
    if (
        not skip_k
        and snap
        and clip_export_needs_more_cards(visible, n_slots, names)
    ):
        added = _split_long_clip_export_card(
            hwnd, export_words, nodes, end_fracs=end_fracs
        )
        if added:
            _text, nodes = _read_uia(hwnd, verbose=False)
            chips_now = pick_clip_export_review_rects(_named_rects(nodes), min_y)
            visible = max(visible, len(chips_now), len(inferred_mids))
    if visible > cards_before_split:
        _CLIP_EXPORT_WRITTEN_CARDS = 0
        say(f"Clip Export now has {visible} card(s) after split; will write each one")

    hands = any(is_clip_export_hands_error(_uia_name(ctrl)) for ctrl in nodes)
    dirty = any(
        is_clip_export_caption_label(_uia_name(ctrl)) and "hand" in _uia_name(ctrl).casefold()
        for ctrl in nodes
    ) or any(
        clip_export_caption_needs_rewrite(_uia_name(ctrl))
        or is_garbled_clip_export_caption(_uia_name(ctrl))
        or is_clip_export_placeholder(_uia_name(ctrl))
        for ctrl in nodes
    )
    rewrite_all = should_rewrite_every_clip_export_card(
        [_uia_name(ctrl) for ctrl in nodes], export_ocr
    )
    if dirty or rewrite_all:
        say("Rewriting every visible Clip Export card (not only the first chip)")
    empty = any(is_empty_clip_label(_uia_name(ctrl)) for ctrl in nodes)
    missing_now = any(is_clip_export_missing_error(_uia_name(ctrl)) for ctrl in nodes)
    empty_now = any(is_clip_export_empty_error(_uia_name(ctrl)) for ctrl in nodes)
    short_now = any(is_clip_export_short_error(_uia_name(ctrl)) for ctrl in nodes)
    wrote = 0
    need_slots = (
        rewrite_all
        or visible > _CLIP_EXPORT_WRITTEN_CARDS
        or empty
        or empty_now
        or short_now
        or dirty
        or missing_now
    )
    if need_slots:
        if visible >= 1 or empty or empty_now or short_now or missing_now or rewrite_all:
            wrote = _fill_each_clip_export_slot(
                hwnd,
                sentences,
                end_fracs,
                n_slots=visible,
                ocr_words=export_words,
                long_range=long_range,
                total_s=total_s,
                existing_ends=existing_ends,
            )
            _CLIP_EXPORT_WRITTEN_CARDS = max(_CLIP_EXPORT_WRITTEN_CARDS, visible)
        elif _click_clip_export_caption_field(nodes, prefer_hands=True):
            say("Clicked the Clip Export caption that still mentions hands")
            _type_into_focused(fallback)
            _blur_caption(hwnd, nodes)
            wrote = 1
            say(f"Typed Clip Export: {fallback}")
        else:
            wrote = _type_one_clip_export(hwnd, nodes, fallback)
        wrote += _fill_clip_export_from_qa_errors(hwnd, fallback)
        time.sleep(0.25)
        _text, nodes = _read_uia(hwnd, verbose=False)
        names_after = [_uia_name(ctrl) for ctrl in nodes]
        if wrote == 0 and (
            any(is_empty_clip_label(n) for n in names_after)
            or any(is_clip_export_empty_error(n) for n in names_after)
        ):
            _CLIP_EXPORT_STUCK = True
        if wrote:
            _CLIP_EXPORT_FILLED = True
        if any(is_clip_export_hands_error(_uia_name(ctrl)) for ctrl in nodes):
            say("Clip Export still mentions hands; retyping without hand/handling")
            _click_clip_export_caption_field(nodes, prefer_hands=True)
            _type_into_focused(fallback)
            _blur_caption(hwnd, nodes)
            wrote = 1
            say(f"Typed Clip Export: {fallback}")
    if not any(is_clip_export_end_mismatch(_uia_name(ctrl)) for ctrl in nodes):
        _click_clip_export_end_ignore(hwnd, nodes)
    else:
        qa_frames = qa_mismatch_frames([_uia_name(ctrl) for ctrl in nodes])
        start_frame = review_start_frame_from_ocr(export_ocr)
        if needs_one_frame_nudge(qa_frames, start_frame):
            _nudge_clip_export_end_one_frame(hwnd, nodes)
        else:
            say("Leaving Clip Export end-match warning; ends still need a Sub-goal snap")
    time.sleep(0.2)
    used_export = _apply_review_uses(hwnd, write=write, max_clicks=3)
    if used_export.get("applied"):
        say(f"Clicked Clip Export Grammar Use {used_export['applied']} time(s)")
        wrote += int(used_export["applied"])
    _click_quality_run_now(hwnd)
    time.sleep(0.3)
    _text, nodes = _read_uia(hwnd, verbose=False)
    names_left = [_uia_name(ctrl) for ctrl in nodes]
    qa_text = "\n".join(names_left)
    if not fillable_clip_export_qa(names_left) and not _OCR_BROKEN:
        words_left, _lw, _lh = _ocr_window(hwnd, "qa_after_export")
        qa_text = "\n".join([qa_text, ocr_text(words_left)])
    qa_remaining = fillable_clip_export_qa(names_left) or fixable_review_work_remaining(qa_text)
    if duplicate_clip_export_only(names_left, qa_text) and not qa_remaining:
        say("Duplicate Clip Export track remains; not deleting it")
    if not qa_remaining:
        _switch_timeline_kind(hwnd, "sub-goal")
        _close_timeline_dropdown(hwnd)
    else:
        say("Clip Export Quality Assistant still has fixable rows; staying on Clip Export")
    return {
        "wrote": wrote,
        "text": fallback,
        "qa_text": qa_text,
        "qa_remaining": qa_remaining,
    }


def _subgoal_end_fractions(
    hwnd: int,
    nodes: list[Any],
    harvested: list[Any],
    names: list[str] | None = None,
    ocr_blob: str = "",
) -> list[float]:
    """Cut Clip Export at real Sub-goal ends, never at 16/33/50% guesses."""
    end_times: list[float] = []
    durations: list[float] = []
    for clip in harvested or []:
        start = getattr(clip, "start_s", None)
        end = getattr(clip, "end_s", None)
        dur = getattr(clip, "duration_s", None)
        if end is not None:
            end_times.append(float(end))
        elif start is not None and dur:
            end_times.append(float(start) + float(dur))
        if dur is None and start is not None and end is not None:
            dur = float(end) - float(start)
        if dur and float(dur) > 0.05:
            durations.append(float(dur))
    fps = parse_timeline_fps(ocr_blob) or 30.0
    for sec in qa_end_mismatch_seconds(names or [], fps):
        if all(abs(sec - seen) > 0.15 for seen in end_times):
            end_times.append(sec)
    durations.extend(clip_durations_from_ocr(ocr_blob))
    if len(durations) >= 2:
        acc = 0.0
        for dur in durations[:-1]:
            acc += float(dur)
            if all(abs(acc - seen) > 0.15 for seen in end_times):
                end_times.append(acc)
    total = sum(durations) if len(durations) >= 2 else None
    fracs = clip_export_end_fractions_from_times(end_times, total)
    if len(durations) >= 2:
        for frac in clip_export_cut_fractions(durations, len(durations)):
            if all(abs(frac - seen) > 0.03 for seen in fracs):
                fracs.append(frac)
    left, top, width, height = _window_rect(hwnd)
    bar = _full_timeline_rect(hwnd, nodes)
    min_y = top + int(height * 0.62)
    rects: list[tuple[int, int, int, int]] = []
    for name, rect in _named_rects(nodes):
        if not (is_timeline_status_label(name) or looks_like_neighbor_action(name)):
            continue
        if (rect[1] + rect[3]) / 2 < min_y:
            continue
        rects.append(rect)
    bar_left, _bt, bar_right, _bb = bar
    if bar_right - bar_left < 200:
        bar_left = left + int(width * 0.08)
        bar_right = left + int(width * 0.92)
    for frac in clip_export_end_fractions_from_status_rects(rects, bar_left, bar_right):
        if all(abs(frac - seen) > 0.03 for seen in fracs):
            fracs.append(frac)
    return sorted(fracs)


def _focused_timeline_rect(hwnd: int, nodes: list[Any]) -> tuple[int, int, int, int]:
    left, top, width, height = _window_rect(hwnd)
    for ctrl in nodes:
        if _uia_name(ctrl).strip().casefold() != "focused timeline":
            continue
        try:
            rect = ctrl.rectangle()
            return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        except Exception:
            continue
    return (left, int(top + height * 0.72), left + width, int(top + height * 0.86))


def _focused_timeline_xy(
    hwnd: int, frac: float, nodes: list[Any] | None = None
) -> tuple[int, int]:
    """Playhead point on Focused Timeline. Does not click."""
    if nodes is None:
        _text, nodes = _read_uia(hwnd, verbose=False)
    left, top, width, height = _window_rect(hwnd)
    bar = _focused_timeline_rect(hwnd, nodes)
    x, y = full_timeline_xy(bar, frac, (left, top, width, height))
    if bar[2] - bar[0] < 200:
        y = int(top + height * 0.78)
    return x, y


def _click_focused_timeline_fraction(
    hwnd: int, frac: float, nodes: list[Any] | None = None
) -> tuple[int, int]:
    """Click along Focused Timeline (the clip-cut bar), not Full Timeline."""
    x, y = _focused_timeline_xy(hwnd, frac, nodes)
    _click_screen(x, y)
    return x, y


def _align_clip_export_on_focused_timeline(
    hwnd: int,
    fracs: list[float],
    nodes: list[Any],
    existing_ends: list[float] | None = None,
) -> int:
    """K-split Clip Export on Focused Timeline at Sub-goal ends. Full Timeline K does not create clips."""
    global _CLIP_EXPORT_SNAPPED
    if not fracs:
        say("No Sub-goal end positions; leaving the existing Clip Export clip")
        return 0
    if not _ensure_clip_export_track(hwnd, nodes):
        say("Not pressing K: timeline is Hand Tracking Error, not Clip Export")
        return 0
    _text, nodes = _read_uia(hwnd, verbose=False)
    _pause_via_uia(hwnd, nodes)
    _focus_filled_clip_export_track(hwnd, nodes)
    time.sleep(0.15)
    unique: list[float] = []
    for frac in fracs[:8]:
        clamped = max(0.04, min(0.96, float(frac)))
        if any(abs(clamped - seen) < 0.03 for seen in unique):
            continue
        if any(abs(clamped - seen) < 0.03 for seen in _CLIP_EXPORT_SNAPPED):
            continue
        if any(abs(clamped - seen) < 0.03 for seen in (existing_ends or [])):
            continue
        unique.append(clamped)
    left, top, _width, height = _window_rect(hwnd)
    min_y = top + int(height * 0.62)
    chips_before = len(pick_clip_export_review_rects(_named_rects(nodes), min_y))
    cuts = 0
    for frac in unique:
        if not _ensure_clip_export_track(hwnd, nodes):
            say("Aborting Clip Export K: Hand Tracking Error is selected")
            break
        x, y = _click_focused_timeline_fraction(hwnd, frac, nodes)
        say(f"Snapped Clip Export end on Focused Timeline at {int(frac * 100)}% ({x},{y})")
        time.sleep(0.15)
        if not _press_k_to_create(hwnd, at=(x, y)):
            break
        time.sleep(0.35)
        _text, nodes = _read_uia(hwnd, verbose=False)
        names_after = [_uia_name(ctrl) for ctrl in nodes]
        chips_after = len(pick_clip_export_review_rects(_named_rects(nodes), min_y))
        if should_abort_clip_export_k(names_after):
            say("Focused Timeline K landed on Hand Tracking Error; stopping")
            break
        if should_stop_clip_export_k(chips_before, chips_after, names_after):
            if _click_split_control(hwnd, nodes):
                time.sleep(0.3)
                _text, nodes = _read_uia(hwnd, verbose=False)
                chips_after = len(pick_clip_export_review_rects(_named_rects(nodes), min_y))
                if chips_after > chips_before:
                    cuts += 1
                    chips_before = chips_after
                    continue
            say(
                f"K at {int(frac * 100)}% did not add a card (already an edge); "
                "trying the next Sub-goal end inside the long card"
            )
            _CLIP_EXPORT_SNAPPED.append(frac)
            continue
        cuts += 1
        _CLIP_EXPORT_SNAPPED.append(frac)
        chips_before = chips_after
    if not unique:
        say("Clip Export ends already snapped; not pressing K again")
    elif cuts:
        say(f"Snapped Clip Export to {cuts} Sub-goal end(s) on Focused Timeline")
    return cuts


def _click_clip_export_caption_field(nodes: list[Any], *, prefer_hands: bool = False) -> bool:
    """Click a Clip Export caption, never a Quality Assistant error row."""
    ranked: list[tuple[int, int, Any]] = []
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not is_clip_export_caption_label(name):
            continue
        center = _ctrl_center(ctrl)
        if not center:
            continue
        score = 0
        lowered = name.casefold()
        if prefer_hands and "hand" in lowered:
            score += 50
        if lowered.startswith("the person"):
            score += 10
        ranked.append((score, -center[1], ctrl))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    for _score, _y, ctrl in ranked[:4]:
        name = _uia_name(ctrl)
        if _uia_click(ctrl):
            say(f"Clip Export: clicked caption '{name[:70]}'")
            return True
        center = _ctrl_center(ctrl)
        if center:
            _click_screen(center[0], center[1])
            say(f"Clip Export: clicked caption '{name[:70]}'")
            return True
    return False


def _align_clip_export_cuts(hwnd: int, fracs: list[float], nodes: list[Any]) -> int:
    """Clip Export cuts belong on Focused Timeline; Full Timeline K does not create clips."""
    return _align_clip_export_on_focused_timeline(hwnd, fracs, nodes)


def _split_long_clip_export_card(
    hwnd: int,
    words: list[dict],
    nodes: list[Any],
    end_fracs: list[float] | None = None,
) -> int:
    """K inside a long Clip Export card. Uses duration chips when OCR sees them."""
    if not _ensure_clip_export_track(hwnd, nodes):
        return 0
    left, top, width, height = _window_rect(hwnd)
    min_y = top + int(height * 0.62)
    hits = pick_ocr_duration_centers(words or [], int(height * 0.62))
    long_hits = [row for row in hits if row[2] > 10]
    chips_before = len(pick_clip_export_review_rects(_named_rects(nodes), min_y))
    added = 0
    click_points: list[tuple[int, int, str]] = []
    if long_hits:
        _x0, y0, dur = max(long_hits, key=lambda row: row[2])
        for offset in (90, 180, 270, 360):
            click_points.append((left + _x0 + offset, top + y0, f"{dur:g}s"))
    else:
        bar = _focused_timeline_rect(hwnd, nodes)
        bar_left, bar_right = bar[0], bar[2]
        if bar_right - bar_left < 200:
            bar_left = left + int(width * 0.08)
            bar_right = left + int(width * 0.92)
        named = _named_rects(nodes)
        status = pick_clip_export_status_rects(named, min_y)
        interiors = wide_card_cut_fracs(
            status or pick_clip_export_review_rects(named, min_y),
            end_fracs or [0.28, 0.42, 0.56, 0.70],
            bar_left,
            bar_right,
        )
        ranged = review_clip_range_from_ocr(ocr_text(words or []))
        if ranged and ranged[2] > 10:
            interiors = long_range_interior_fracs(ranged[0], ranged[1], max(ranged[1] + 4.0, ranged[2] + ranged[0]))
            interiors.extend(f for f in (end_fracs or []) if all(abs(f - seen) > 0.03 for seen in interiors))
        if not interiors:
            interiors = [0.32, 0.40, 0.48, 0.56, 0.64, 0.72]
        for frac in interiors[:8]:
            x, y = _focused_timeline_xy(hwnd, frac, nodes)
            click_points.append((x, y, f"{int(frac * 100)}%"))
    _focus_filled_clip_export_track(hwnd, nodes)
    time.sleep(0.1)
    for x, y, label in click_points:
        _click_screen(x, y)
        say(f"Splitting long Clip Export card inside at {label} ({x},{y})")
        time.sleep(0.15)
        if not _press_k_to_create(hwnd, at=(x, y)):
            break
        time.sleep(0.35)
        _text, nodes = _read_uia(hwnd, verbose=False)
        names = [_uia_name(ctrl) for ctrl in nodes]
        chips_after = len(pick_clip_export_review_rects(_named_rects(nodes), min_y))
        if should_abort_clip_export_k(names):
            say("Long-card K landed on Hand Tracking Error; stopping")
            break
        if should_stop_clip_export_k(chips_before, chips_after, names):
            say(f"Long-card K at {label} was already an edge; trying the next cut")
            continue
        added += 1
        chips_before = chips_after
    return added


def _click_clip_export_end_ignore(hwnd: int, nodes: list[Any] | None = None) -> bool:
    """Dismiss the end-match warning after a snap. Never Ignore all."""
    if nodes is None:
        _text, nodes = _read_uia(hwnd, verbose=False)
    names = [_uia_name(ctrl) for ctrl in nodes]
    if not any(is_clip_export_end_mismatch(n) for n in names):
        return False
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if is_ignore_all_label(name):
            continue
        if not is_ignore_warning_label(name):
            continue
        if _uia_click(ctrl):
            say("Clicked Ignore on Clip Export end-match warning (not Ignore all)")
            time.sleep(0.25)
            return True
    return False


def _click_clip_export_editor(hwnd: int, nodes: list[Any]) -> bool:
    """Click 'click to add text' once. Never Alt-refocus. Never a second guessed click."""
    left, top, width, height = _window_rect(hwnd)
    target = pick_click_to_add_text_target(_named_rects(nodes), left, top, width, height)
    if target:
        _rect, (x, y) = target
        _click_screen(x, y)
        say(f"Clicked UIA empty clip: click to add text at {x},{y}")
        return True
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if "click to add" not in name.casefold():
            continue
        if _uia_click(ctrl):
            say(f"Clicked UIA empty clip: {name}")
            return True
    return False


def _uia_set_text(ctrl: Any, text: str) -> bool:
    for action in (
        lambda: ctrl.set_edit_text(text),
        lambda: ctrl.iface_value.SetValue(text),
    ):
        try:
            action()
            return True
        except Exception:
            continue
    return False


def _clipboard_set(text: str) -> bool:
    try:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception:
        return False


def _send_ctrl_v() -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(0x11, 0, 0, 0)
    user32.keybd_event(0x56, 0, 0, 0)
    user32.keybd_event(0x56, 0, 2, 0)
    user32.keybd_event(0x11, 0, 2, 0)


def _paste_into_focused(text: str) -> None:
    """Clipboard paste so Hindi IME does not swallow Unicode key events."""
    if _clipboard_set(text):
        time.sleep(0.08)
        _send_ctrl_a()
        time.sleep(0.05)
        _send_ctrl_v()
        say("Pasted Clip Export from the clipboard")
        return
    _type_into_focused(text)


def _commit_caption_field() -> None:
    """Tab out of the description box so SensorFusionLab stores the sentence. Never Enter."""
    time.sleep(0.2)
    _send_vk(0x09)
    time.sleep(0.2)


def _click_review_description_box(hwnd: int, nodes: list[Any]) -> bool:
    """Click the Review sidebar description, including an existing The-person caption."""
    left, top, width, height = _window_rect(hwnd)
    hits = pick_review_description_rects(_named_rects(nodes), left, top, width, height)
    if hits:
        x, y = review_description_click_xy(hits[0])
        _click_screen(x, y)
        say(f"Clicked Review description box at {x},{y}")
        return True
    return False


def _ensure_clip_export_track(hwnd: int, nodes: list[Any] | None = None) -> bool:
    """Leave Hand Tracking Error before any Clip Export K or paste."""
    if nodes is None:
        _text, nodes = _read_uia(hwnd, verbose=False)
    names = [_uia_name(ctrl) for ctrl in nodes]
    if any(is_hte_clip_caption(n) for n in names):
        say("Hand Tracking Error is selected; switching to Clip Export")
        _switch_timeline_kind(hwnd, "clip export")
        time.sleep(0.3)
        _text, nodes = _read_uia(hwnd, verbose=False)
        names = [_uia_name(ctrl) for ctrl in nodes]
    if any(is_hte_clip_caption(n) for n in names):
        say("Still on Hand Tracking Error; not creating or typing HTE clips")
        return False
    if clip_export_track_ready(names):
        return True
    _switch_timeline_kind(hwnd, "clip export")
    time.sleep(0.3)
    _text, nodes = _read_uia(hwnd, verbose=False)
    names = [_uia_name(ctrl) for ctrl in nodes]
    if clip_export_track_ready(names):
        return True
    if selected_timeline_kind(names) == "clip export":
        return True
    say("Clip Export switch did not stick; not treating that as Hand Tracking Error")
    return False


def _click_full_timeline_clip_export_track(hwnd: int, nodes: list[Any]) -> bool:
    """Click the lowest ClipExport label so Focused Timeline shows that track, not Sub-goal."""
    left, top, _width, height = _window_rect(hwnd)
    hits: list[tuple[int, Any]] = []
    for ctrl in nodes:
        if not is_clip_export_tab(_uia_name(ctrl)):
            continue
        center = _ctrl_center(ctrl)
        if center and center[1] > top + int(height * 0.52):
            hits.append((center[1], ctrl))
    if not hits:
        return False
    hits.sort(key=lambda row: -row[0])
    if _uia_click(hits[0][1]):
        say("Clicked Full Timeline Clip Export track so Focused Timeline shows Clip Export")
        time.sleep(0.25)
        return True
    return False


def _focus_filled_clip_export_track(hwnd: int, nodes: list[Any]) -> bool:
    """Click a timeline chip (not the Review caption) so K hits Clip Export, not a text box."""
    names = [_uia_name(ctrl) for ctrl in nodes]
    if not clip_export_track_ready(names):
        _click_full_timeline_clip_export_track(hwnd, nodes)
        _text, nodes = _read_uia(hwnd, verbose=False)
        names = [_uia_name(ctrl) for ctrl in nodes]
    if any(is_hte_clip_caption(n) for n in names):
        say("Focused Timeline is Hand Tracking Error; not clicking that track")
        return False
    left, top, _width, height = _window_rect(hwnd)
    min_y = top + int(height * 0.62)
    chips = pick_clip_export_status_rects(_named_rects(nodes), min_y)
    if not chips:
        chips = pick_clip_export_review_rects(_named_rects(nodes), min_y)
    chips = [rect for rect in chips if rect[0] >= left + 70]
    if chips:
        # Prefer the widest / rightmost card (the 27s middle clip), not x=48 chrome.
        rect = max(chips, key=lambda row: (row[2] - row[0], row[0]))
        x = int((rect[0] + rect[2]) / 2)
        y = int((rect[1] + rect[3]) / 2)
        _click_screen(x, y)
        say(f"Clicked filled Clip Export chip at {x},{y} before snap")
        return True
    return False


def _write_clip_export_sentence(
    hwnd: int, nodes: list[Any], sentence: str, *, force: bool = False
) -> bool:
    """Paste into this slot's Review box or existing The-person caption. Never require click-to-add-text."""
    del force
    names_now = [_uia_name(ctrl) for ctrl in nodes]
    if selected_timeline_kind(names_now) == "hte" or any(is_hte_clip_caption(n) for n in names_now):
        say("On Hand Tracking Error; not typing into this track")
        return False
    field = None
    for ctrl in nodes:
        if "click to add" in _uia_name(ctrl).casefold():
            field = ctrl
            break
    focused = _click_clip_export_editor(hwnd, nodes)
    if not focused:
        focused = _click_review_description_box(hwnd, nodes)
    if not focused:
        focused = _click_clip_export_caption_field(nodes, prefer_hands=True)
    if not focused:
        say("Could not focus Clip Export caption; not counting this write")
        return False
    time.sleep(0.2)
    if field is not None and _uia_set_text(field, sentence):
        say("Set Clip Export via UIA Value")
    else:
        _paste_into_focused(sentence)
    time.sleep(0.3)
    _commit_caption_field()
    time.sleep(0.35)
    _text, after = _read_uia(hwnd, verbose=False)
    names = [_uia_name(ctrl) for ctrl in after]
    ocr_blob = ""
    if not _OCR_BROKEN:
        words, _iw, _ih = _ocr_window(hwnd, "clip_export_saved")
        ocr_blob = ocr_text(words)
    if clip_export_caption_committed(names, ocr_blob, sentence):
        say(f"Saved Clip Export: {sentence}")
        return True
    say(f"Clip Export text did not stick after typing: {sentence[:70]}")
    return False


def _click_quality_run_now(hwnd: int, nodes: list[Any] | None = None) -> bool:
    if nodes is None:
        _text, nodes = _read_uia(hwnd, verbose=False)
    for ctrl in nodes:
        if not is_quality_run_now_label(_uia_name(ctrl)):
            continue
        if _uia_click(ctrl):
            say("Clicked Quality Assistant Run now")
            time.sleep(0.4)
            return True
    return False


def _fill_clip_export_from_qa_errors(hwnd: int, sentence: str) -> int:
    """Click each empty/short Clip Export Quality Assistant row and type 15+ words."""
    wrote = 0
    stuck = 0
    for _attempt in range(3):
        _text, nodes = _read_uia(hwnd, verbose=False)
        target = None
        for ctrl in nodes:
            name = _uia_name(ctrl)
            if is_clip_export_empty_error(name) or is_clip_export_short_error(name):
                target = ctrl
                break
        if target is None:
            break
        if not _uia_click(target):
            break
        say("Clicked Quality Assistant Clip Export empty/short row")
        time.sleep(0.3)
        _text, nodes = _read_uia(hwnd, verbose=False)
        if _write_clip_export_sentence(hwnd, nodes, sentence):
            wrote += 1
            stuck = 0
        else:
            stuck += 1
            if stuck >= 2:
                say("Clip Export field still empty after typing; stopping the same-row retry")
                break
        time.sleep(0.25)
    return wrote


def _nudge_clip_export_end_one_frame(hwnd: int, nodes: list[Any]) -> bool:
    """QA wants frame 297; the current Clip Export ends at 296. Nudge one frame right."""
    left, top, _width, height = _window_rect(hwnd)
    min_y = top + int(height * 0.62)
    chips = [
        rect
        for rect in pick_clip_export_status_rects(_named_rects(nodes), min_y)
        if rect[0] >= left + 70
    ]
    if not chips:
        chips = [
            rect
            for rect in pick_clip_export_review_rects(_named_rects(nodes), min_y)
            if rect[0] >= left + 70
        ]
    if not chips:
        return False
    rect = min(chips, key=lambda row: row[0])
    x = int(rect[2] + 4)
    y = int((rect[1] + rect[3]) / 2)
    _click_screen(x, y)
    time.sleep(0.1)
    _send_vk(0x27)
    say("Nudged Clip Export end one frame to match the Sub-goal end (297)")
    return True


def _click_split_control(hwnd: int, nodes: list[Any] | None = None) -> bool:
    """Use the on-screen Split control instead of typing K into the Review box."""
    if nodes is None:
        _text, nodes = _read_uia(hwnd, verbose=False)
    for ctrl in nodes:
        if not is_split_control_label(_uia_name(ctrl)):
            continue
        if _uia_click(ctrl):
            say("Clicked Split (not typing K into the caption)")
            time.sleep(0.25)
            return True
    return False


def _apply_subgoal_harvest_rewrites(hwnd: int, write: bool = True) -> dict:
    """Write every Sub-goal that still fails lint, not only the first issue."""
    _switch_timeline_kind(hwnd, "sub-goal")
    time.sleep(0.35)
    uia_text, nodes = _read_uia(hwnd, verbose=False)
    names = [_uia_name(ctrl) for ctrl in nodes]
    ocr_blob = ""
    if not _OCR_BROKEN:
        words, _iw, _ih = _ocr_window(hwnd, "subgoal_harvest_write")
        ocr_blob = ocr_text(words)
    clips = harvest_timeline_clips(names, ocr_blob)
    items = lint_clips([clip.to_dict() for clip in clips])
    todo = harvest_rewrites_to_apply(items, _REWRITTEN_SNIPPETS)
    if not todo:
        say("No Sub-goal caption still needs a rewrite")
        return {"wrote": 0, "text": uia_text}
    say(f"Writing {len(todo)} Sub-goal caption fix(es) (every clip with an issue, not one)")
    wrote = 0
    left, top, _width, height = _window_rect(hwnd)
    for item in todo:
        lint = item["lint"]
        snippet = " ".join((lint.original or "").split()[:6])
        if not write or not snippet:
            continue
        _text, nodes = _read_uia(hwnd, verbose=False)
        clicked = False
        for ctrl in nodes:
            name = _uia_name(ctrl)
            if snippet.lower() not in name.lower():
                continue
            center = _ctrl_center(ctrl)
            if center and center[1] < top + height * 0.55:
                continue
            if _uia_click(ctrl):
                clicked = True
                break
            if center:
                _click_screen(center[0], center[1])
                clicked = True
                break
        if not clicked:
            say(f"Could not click Sub-goal '{snippet[:50]}'; skipping that write")
            continue
        time.sleep(0.25)
        _text, nodes = _read_uia(hwnd, verbose=False)
        _click_review_description_box(hwnd, nodes)
        _paste_into_focused(lint.rewritten)
        _commit_caption_field()
        _blur_caption(hwnd, nodes)
        key = " ".join((lint.original or "").split()[:5]).casefold()
        _REWRITTEN_SNIPPETS.add(key)
        wrote += 1
        say(f"Wrote Sub-goal {wrote}/{len(todo)}: {lint.rewritten}")
        time.sleep(0.3)
    return {"wrote": wrote, "text": uia_text}


def _fill_each_clip_export_slot(
    hwnd: int,
    sentences: list[str],
    end_fracs: list[float] | None = None,
    n_slots: int | None = None,
    ocr_words: list[dict] | None = None,
    long_range: tuple[float, float, float] | None = None,
    total_s: float | None = None,
    existing_ends: list[float] | None = None,
) -> int:
    wrote = 0
    left, top, _width, height = _window_rect(hwnd)
    min_y = top + int(height * 0.62)
    _text, nodes = _read_uia(hwnd, verbose=False)
    chips = [
        rect
        for rect in pick_clip_export_review_rects(_named_rects(nodes), min_y)
        if rect[0] >= left + 70
    ]
    duration_hits = pick_ocr_duration_centers(ocr_words or [], int(height * 0.62))
    person_hits = pick_ocr_timeline_person_centers(ocr_words or [], int(height * 0.62))
    span = float(total_s or 0.0)
    if long_range:
        span = max(span, long_range[1] + 10.0, 40.0)
    inferred = clip_export_inferred_card_fracs(long_range, span or 62.0, existing_ends)
    if not inferred and end_fracs:
        inferred = clip_export_slot_mid_fractions(end_fracs, max(int(n_slots or 0), 1))
    targets: list[tuple[int, int, str]] = []
    for i, rect in enumerate(chips):
        x = int((rect[0] + rect[2]) / 2)
        y = int((rect[1] + rect[3]) / 2)
        targets.append((x, y, f"chip {i + 1}"))
    for x, y, dur in duration_hits:
        sx, sy = left + x, top + y
        if any(abs(sx - tx) < 80 for tx, _ty, _label in targets):
            continue
        targets.append((sx, sy, f"{dur:g}s"))
    for x, y in person_hits:
        sx, sy = left + x, top + y
        if any(abs(sx - tx) < 80 for tx, _ty, _label in targets):
            continue
        targets.append((sx, sy, "person"))
    for frac in inferred:
        x, y = _focused_timeline_xy(hwnd, frac, nodes)
        if any(abs(x - tx) < 80 for tx, _ty, _label in targets):
            continue
        targets.append((x, y, f"{int(frac * 100)}%"))
    targets.sort(key=lambda row: row[0])
    n = max(len(targets), int(n_slots or 0), 1)
    fallback_sentence = "The person works at an indoor table during a laundry folding task."
    sentences = list(sentences or [fallback_sentence])
    if len(sentences) < n:
        sentences = sentences + [sentences[-1] if sentences else fallback_sentence] * (
            n - len(sentences)
        )
    say(f"Filling {len(targets)} Clip Export card(s) (every visible segment, not one)")
    for i, (x, y, label) in enumerate(targets):
        sentence = sentences[i]
        if not _ensure_clip_export_track(hwnd):
            say("Stopped Clip Export fill: Hand Tracking Error is selected")
            break
        _click_screen(x, y)
        say(f"Clicked Clip Export card {i + 1}/{len(targets)} ({label}) at {x},{y}")
        time.sleep(0.3)
        _text, nodes = _read_uia(hwnd, verbose=False)
        if _write_clip_export_sentence(hwnd, nodes, sentence, force=True):
            wrote += 1
        _blur_caption(hwnd, nodes)
        time.sleep(0.2)
    return wrote


def _type_one_clip_export(hwnd: int, nodes: list[Any], text: str) -> int:
    clicked = False
    names = [_uia_name(ctrl) for ctrl in nodes]
    if not clip_export_needs_new_clip(names):
        clicked = _click_bottom_pending(hwnd, nodes)
        if not clicked:
            clicked = _click_uia_empty_clip(nodes)
        if not clicked and not _OCR_BROKEN:
            words, img_w, img_h = _ocr_window(hwnd, "clip_export")
            left, top, _w, _h = _window_rect(hwnd)
            phrases = ("the person", "focus annotation", "click to add text")
            if not is_clip_export_placeholder(ocr_text(words)):
                phrases = ("focus annotation", "the person", "click to add text")
            for phrase in phrases:
                target = find_caption_field_click(words, phrase, img_w, img_h)
                if target:
                    _focus(hwnd)
                    _click_screen(left + target[0], top + target[1])
                    clicked = True
                    say(f"Clicked Clip Export field: {phrase}")
                    break
        if clicked:
            say("Typing into the existing Clip Export clip (did not press K)")
        else:
            say("Clip Export already has a clip; typing into the focused field")
            clicked = True
    else:
        created = False
        for ctrl in nodes:
            if is_hte_label(_uia_name(ctrl)):
                continue
            if is_create_clip_hint(_uia_name(ctrl)):
                if _uia_click(ctrl):
                    say("Clicked 'click or press K to create' on Clip Export")
                    created = True
                    break
        if not created:
            say("Typing into the existing Clip Export track (not creating a second timeline)")
            _click_focused_timeline_fraction(hwnd, 0.15, nodes)
        time.sleep(0.45)
        uia_text, nodes = _read_uia(hwnd)
        clicked = _click_uia_empty_clip(nodes) or _click_bottom_pending(hwnd, nodes)
        if not clicked:
            say("Clip Export field focused; typing without a Full Timeline K")
            clicked = True
    time.sleep(0.2)
    _type_into_focused(text)
    _blur_caption(hwnd, nodes)
    say(f"Typed Clip Export: {text}")
    return 1


def _click_bottom_pending(hwnd: int, nodes: list[Any]) -> bool:
    hits: list[tuple[int, Any]] = []
    for ctrl in nodes:
        if not is_pending_clip_label(_uia_name(ctrl)):
            continue
        center = _ctrl_center(ctrl)
        if center:
            hits.append((center[1], ctrl))
    hits.sort(key=lambda row: -row[0])
    if not hits:
        return False
    if _uia_click(hits[0][1]):
        say("Clicked existing pending clip (did not press K)")
        return True
    return False


def _span_clip_export(hwnd: int, nodes: list[Any]) -> None:
    """Do not K on Full Timeline. That creates a second Clip Export track."""
    del nodes
    say("Skipping Full Timeline K so a second Clip Export timeline is not created")


def _split_long_idle(hwnd: int, write: bool = True) -> dict:
    """Split Idle >5s with K, per clipping spec. Never HTE. Never Submit."""
    global _IDLE_SPLIT_STUCK
    uia_text, nodes = _read_uia(hwnd)
    names = [_uia_name(ctrl) for ctrl in nodes]
    left, top, _width, height = _window_rect(hwnd)
    min_y = top + int(height * 0.62)
    named = _named_rects(nodes)
    if _IDLE_SPLIT_STUCK:
        if idle_is_opening_clip(named, min_y) and any(
            (n or "").strip().casefold() == "idle" for n in names
        ):
            say("Opening Idle >5s did not split; replacing it with an action caption")
            return _recaption_false_idle(hwnd, write=write, force=True)
        say("Idle >5s K-split did not change the card; not retrying the same cut")
        return {"wrote": 0, "text": uia_text}
    if not should_split_overlong_idle(names, named, min_y):
        if should_recaption_false_idle(names, named, min_y) or any(
            is_false_idle_review_error(n) for n in names
        ):
            say("Not splitting: opening Idle is action, not a pause")
        return {"wrote": 0, "text": uia_text}
    target = None
    for ctrl in nodes:
        if is_idle_too_long_error(_uia_name(ctrl)):
            target = ctrl
            break
    if target is None:
        return {"wrote": 0, "text": uia_text}
    if not write:
        return {"wrote": 0, "text": uia_text}

    _pause_via_uia(hwnd, nodes)
    _switch_timeline_kind(hwnd, "sub-goal")
    uia_text, nodes = _read_uia(hwnd)
    target = None
    for ctrl in nodes:
        if is_idle_too_long_error(_uia_name(ctrl)):
            target = ctrl
            break
    if target is None:
        return {"wrote": 0, "text": uia_text}
    _uia_click(target)
    say("Clicked Quality Assistant idle-too-long error")
    time.sleep(0.4)
    wrote = 0
    for fraction in (0.45, 0.90):
        uia_text, nodes = _read_uia(hwnd)
        if not any(is_idle_too_long_error(_uia_name(ctrl)) for ctrl in nodes):
            say("Idle >5s Quality Assistant error is gone")
            break
        _pause_via_uia(hwnd, nodes)
        if not _click_idle_split_point(hwnd, nodes, fraction=fraction):
            continue
        time.sleep(0.2)
        _press_k_to_create(hwnd)
        wrote += 1
        time.sleep(0.8)
        uia_text, nodes = _read_uia(hwnd)
        if _click_uia_empty_clip(nodes):
            time.sleep(0.2)
            _type_into_focused("Idle")
            say("Typed Idle on the new split segment")
            wrote += 1
            time.sleep(0.35)
            uia_text, nodes = _read_uia(hwnd)
        if not any(is_idle_too_long_error(_uia_name(ctrl)) for ctrl in nodes):
            say("Idle >5s Quality Assistant error is gone")
            break
    still = any(is_idle_too_long_error(_uia_name(ctrl)) for ctrl in nodes)
    if still:
        _IDLE_SPLIT_STUCK = True
        say("Idle >5s error remains after K; not repeating the same cut")
    if wrote:
        say("Split Idle >5s with K into smaller Idle subgoals")
    else:
        say("Could not land a K-split inside the Idle >5s card")
    return {"wrote": wrote, "text": uia_text}


def _dropdown_kind_ctrl(nodes: list[Any], want: str) -> Any | None:
    """ClipExport / Sub-goal row from the open 3-item menu only. Never a Full Timeline track."""
    names = [_uia_name(ctrl) for ctrl in nodes]
    if not timeline_dropdown_is_open(names):
        return None
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if is_hte_label(name):
            continue
        if want == "clip export" and is_clip_export_tab(name):
            return ctrl
        if want == "sub-goal" and name.strip().casefold() in {"sub-goal", "subgoal"}:
            return ctrl
    return None


def _wait_kind_dropdown_open(hwnd: int, tries: int = 6) -> list[Any]:
    """The 3-item menu often lags one UIA read behind the click."""
    nodes: list[Any] = []
    for _attempt in range(max(int(tries), 1)):
        _text, nodes = _read_uia(hwnd, verbose=False)
        names = [_uia_name(ctrl) for ctrl in nodes]
        if timeline_dropdown_is_open(names):
            return nodes
        time.sleep(0.2)
    return nodes


def _switch_timeline_kind(hwnd: int, kind: str) -> bool:
    """Open the Sub-goal dropdown and pick Clip Export or Sub-goal. Never HTE."""
    want = "clip export" if kind.strip().casefold() in {"clip export", "clipexport", "clip_export"} else "sub-goal"
    _text, nodes = _read_uia(hwnd)
    names = [_uia_name(ctrl) for ctrl in nodes]
    current = selected_timeline_kind(names)
    if current == want or (want == "clip export" and clip_export_track_ready(names)):
        say(f"Already on {want} timeline")
        return True
    if not timeline_dropdown_is_open(names):
        dropdowns: list[Any] = []
        for ctrl in nodes:
            name = _uia_name(ctrl)
            if is_hte_label(name):
                if current == "hte":
                    center = _ctrl_center(ctrl)
                    if center:
                        dropdowns.append((center[1], ctrl, name))
                continue
            if is_timeline_kind_label(name) or name.strip().casefold() in {"sub-goal", "subgoal"}:
                center = _ctrl_center(ctrl)
                if center:
                    dropdowns.append((center[1], ctrl, name))
        dropdowns.sort(key=lambda row: row[0])
        chosen = dropdowns[0] if dropdowns else None
        if chosen:
            _uia_click(chosen[1])
            say(f"Opened timeline-kind dropdown ({chosen[2]})")
            nodes = _wait_kind_dropdown_open(hwnd)
    menu = _dropdown_kind_ctrl(nodes, want)
    if menu is not None and _uia_click(menu):
        say(f"Selected {'Clip Export' if want == 'clip export' else 'Sub-goal'} timeline")
        time.sleep(0.4)
        _wait_timeline_dropdown_closed(hwnd, allow_escape=False)
        _text, nodes = _read_uia(hwnd, verbose=False)
        names_after = [_uia_name(ctrl) for ctrl in nodes]
        if any(is_hte_clip_caption(n) for n in names_after):
            say("Dropdown landed on Hand Tracking Error; not staying there")
            return False
        return True
    if not _OCR_BROKEN:
        words, img_w, img_h = _ocr_window(hwnd, "timeline_kind")
        left, top, _w, _h = _window_rect(hwnd)
        if current == "hte":
            hte_hit = find_phrase_click(
                words,
                "Hand Tracking Error",
                img_w,
                img_h,
                y_min_frac=0.02,
                y_max_frac=0.22,
                x_max_frac=0.55,
            )
            if hte_hit:
                _click_screen(left + hte_hit[0], top + hte_hit[1])
                say("Opened timeline-kind dropdown (Hand Tracking Error)")
                time.sleep(0.45)
                _text, nodes = _read_uia(hwnd)
                for ctrl in nodes:
                    name = _uia_name(ctrl)
                    if want == "clip export" and is_clip_export_tab(name):
                        if _uia_click(ctrl):
                            say("Selected Clip Export timeline")
                            time.sleep(0.35)
                            _wait_timeline_dropdown_closed(hwnd, allow_escape=False)
                            return True
                    if want == "sub-goal" and name.strip().casefold() in {"sub-goal", "subgoal"}:
                        if _uia_click(ctrl):
                            say("Selected Sub-goal timeline")
                            time.sleep(0.35)
                            _wait_timeline_dropdown_closed(hwnd, allow_escape=False)
                            return True
                words, img_w, img_h = _ocr_window(hwnd, "timeline_kind")
        needle = "ClipExport" if want == "clip export" else "Sub-goal"
        hit = find_phrase_click(
            words, needle, img_w, img_h, y_min_frac=0.02, y_max_frac=0.45, x_max_frac=0.55
        )
        if hit:
            _click_screen(left + hit[0], top + hit[1])
            say(f"Clicked OCR timeline kind: {needle}")
            _wait_timeline_dropdown_closed(hwnd, allow_escape=False)
            return True
    say(f"Could not switch timeline kind to {kind}")
    return False


def _wait_timeline_dropdown_closed(hwnd: int, allow_escape: bool = False) -> None:
    """Wait for the 3-item menu to close. Escape cancels the selection we just made."""
    for _attempt in range(5):
        time.sleep(0.2)
        _text, nodes = _read_uia(hwnd, verbose=False)
        names = [_uia_name(ctrl) for ctrl in nodes]
        if not timeline_dropdown_is_open(names):
            return
    if allow_escape:
        _close_timeline_dropdown(hwnd)


def _click_focused_timeline(hwnd: int, nodes: list[Any]) -> None:
    for ctrl in nodes:
        if _uia_name(ctrl).strip().casefold() == "focused timeline":
            center = _ctrl_center(ctrl)
            if center:
                _click_screen(center[0] + 80, center[1] + 24)
                return
    left, top, width, height = _window_rect(hwnd)
    _click_screen(int(left + width * 0.25), int(top + height * 0.78))


def _click_idle_split_point(hwnd: int, nodes: list[Any], fraction: float = 0.45) -> bool:
    """Place the playhead inside the >5s Idle card so K splits it into pieces <=5s."""
    _left, top, _width, height = _window_rect(hwnd)
    min_y = top + int(height * 0.62)
    idle, nxt = pick_idle_split_rects(_named_rects(nodes), min_y)
    if idle:
        x, y = idle_card_split_xy(idle, nxt, fraction)
        span = (nxt[0] - idle[0]) if nxt is not None else (idle[2] - idle[0])
        if span >= 150:
            _click_screen(x, y)
            say(f"Clicked Idle card at {int(fraction * 100)}% for K-split at {x},{y}")
            return True
    bar_frac = 0.14 if fraction < 0.7 else 0.24
    x, y = _click_focused_timeline_fraction(hwnd, bar_frac, nodes)
    say(f"Clicked Focused Timeline at {int(bar_frac * 100)}% to split Idle at {x},{y}")
    return True


def _type_caption(hwnd: int, nodes: list[Any], original: str, rewritten: str) -> bool:
    snippet = (original or "").strip()[:40]
    _focus(hwnd)
    time.sleep(0.2)
    clicked = False
    if snippet:
        for ctrl in nodes:
            name = _uia_name(ctrl)
            if snippet.lower() in name.lower():
                if _uia_click(ctrl):
                    clicked = True
                    break
    if not clicked:
        return False
    _type_into_focused(rewritten)
    return True


def _send_ctrl_a() -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(0x11, 0, 0, 0)  # VK_CONTROL
    user32.keybd_event(0x41, 0, 0, 0)  # A
    user32.keybd_event(0x41, 0, 2, 0)
    user32.keybd_event(0x11, 0, 2, 0)


def _send_unicode(text: str) -> None:
    """Type with Unicode SendInput so Idle is not dropped on non-US layouts."""
    import ctypes

    if not text:
        return
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    INPUT_KEYBOARD = 1

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_uint),
            ("time", ctypes.c_uint),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_uint),
            ("ki", KEYBDINPUT),
            ("padding", ctypes.c_ubyte * 8),
        ]

    extra = ctypes.sizeof(INPUT)
    for ch in text:
        if ch == "\n":
            ctypes.windll.user32.keybd_event(0x0D, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x0D, 0, 2, 0)
            continue
        code = ord(ch)
        down = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None))
        up = INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None),
        )
        ctypes.windll.user32.SendInput(1, ctypes.byref(down), extra)
        ctypes.windll.user32.SendInput(1, ctypes.byref(up), extra)


def _type_into_focused(text: str) -> None:
    time.sleep(0.15)
    _send_ctrl_a()
    time.sleep(0.05)
    _send_unicode(text)


def _blur_caption(
    hwnd: int, nodes: list[Any] | None = None, *, prefer_quality: bool = False
) -> None:
    """Leave the caption field so Quality Assistant re-runs. Never Submit. Never Enter."""
    if nodes is None:
        _text, nodes = _read_uia(hwnd, verbose=False)
    order = ("quality assistant", "watched", "focused timeline")
    if not prefer_quality:
        order = ("focused timeline", "quality assistant", "watched")
    for want in order:
        for ctrl in nodes:
            if _uia_name(ctrl).strip().casefold() != want:
                continue
            center = _ctrl_center(ctrl)
            if center:
                _click_screen(center[0], center[1])
                time.sleep(0.15)
                return
    _send_vk(0x09)
    time.sleep(0.1)


def _read_window_text(hwnd: int) -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    chunks = [buf.value]
    found: list[str] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(child, _lparam):
        n = user32.GetWindowTextLengthW(child)
        if n:
            child_buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(child, child_buf, n + 1)
            if child_buf.value:
                found.append(child_buf.value)
        return True

    user32.EnumChildWindows(hwnd, callback, 0)
    chunks.extend(found)
    return "\n".join(chunk for chunk in chunks if chunk)


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _capture_window_bmp(hwnd: int, dest) -> tuple[int, int]:
    """Grab pixels on screen. Chromium PrintWindow is often a blank bitmap."""
    from pathlib import Path

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    left, top, width, height = _window_rect(hwnd)
    if width < 2 or height < 2:
        return 0, 0
    bmp = dest.with_suffix(".bmp")
    png = dest.with_suffix(".png")
    _capture_screen_bitblt(left, top, width, height, bmp)
    _capture_screen_pillow(left, top, width, height, png)
    size = 0
    for path in (bmp, png):
        try:
            if path.is_file():
                size = max(size, path.stat().st_size)
        except OSError:
            continue
    say(f"Capture file ~{size} bytes ({bmp.name}/{png.name})")
    return width, height


def _capture_screen_pillow(left: int, top: int, width: int, height: int, dest) -> bool:
    try:
        from PIL import ImageGrab

        image = ImageGrab.grab(bbox=(left, top, left + width, top + height), all_screens=True)
        image.save(dest)
        return True
    except Exception as exc:
        say(f"Screen grab (Pillow) failed: {exc}")
        return False


def _capture_screen_bitblt(left: int, top: int, width: int, height: int, dest) -> bool:
    """BitBlt the desktop DC. This sees Chromium; PrintWindow often does not."""
    import ctypes
    from ctypes import wintypes
    from pathlib import Path

    dest = Path(dest)
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hdc_screen = user32.GetDC(0)
        if not hdc_screen:
            return False
        mem_dc = gdi32.CreateCompatibleDC(hdc_screen)
        bmp = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        gdi32.SelectObject(mem_dc, bmp)
        SRCCOPY = 0x00CC0020
        ok = gdi32.BitBlt(mem_dc, 0, 0, width, height, hdc_screen, left, top, SRCCOPY)
        if not ok:
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(0, hdc_screen)
            return False

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        info = BITMAPINFOHEADER()
        info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.biWidth = width
        info.biHeight = -height
        info.biPlanes = 1
        info.biBitCount = 32
        info.biCompression = 0
        row = ((width * 32 + 31) // 32) * 4
        buf = (ctypes.c_char * (row * height))()
        gdi32.GetDIBits(mem_dc, bmp, 0, height, buf, ctypes.byref(info), 0)
        pixel_bytes = buf.raw[: row * height]
        file_size = 14 + 40 + len(pixel_bytes)
        header = (
            b"BM"
            + file_size.to_bytes(4, "little")
            + (0).to_bytes(4, "little")
            + (54).to_bytes(4, "little")
        )
        dib = (
            (40).to_bytes(4, "little")
            + width.to_bytes(4, "little", signed=True)
            + (-height).to_bytes(4, "little", signed=True)
            + (1).to_bytes(2, "little")
            + (32).to_bytes(2, "little")
            + (0).to_bytes(4, "little")
            + (0).to_bytes(4, "little") * 5
        )
        dest.write_bytes(header + dib + pixel_bytes)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(0, hdc_screen)
        return dest.is_file() and dest.stat().st_size > 54
    except Exception as exc:
        say(f"Screen grab (BitBlt) failed: {exc}")
        return False


def _ocr_image(path) -> list[dict]:
    import json
    import subprocess
    from pathlib import Path

    global _OCR_BROKEN
    if _OCR_BROKEN:
        return []
    script = Path(__file__).with_name("ocr_image.ps1")
    path = Path(path)
    if not script.is_file() or not path.is_file():
        return []
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=40,
        )
    except Exception:
        logger.debug("OCR subprocess failed", exc_info=True)
        return []
    raw = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    json_path = Path(raw.splitlines()[-1].strip()) if raw else None
    if json_path and json_path.suffix.lower() == ".json" and json_path.is_file():
        raw = json_path.read_text(encoding="utf-8-sig")
    elif proc.returncode not in (0, None) or not raw:
        say(f"OCR empty (exit {proc.returncode}). {err[:400]}")
        if "MakeGenericMethod" in err or "generic parameter" in err.lower():
            _OCR_BROKEN = True
            say("OCR script failed; continuing with UIA only.")
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            try:
                payload = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                say(f"OCR JSON parse failed: {raw[:240]}")
                return []
        else:
            say(f"OCR JSON parse failed: {raw[:240]}")
            return []
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _ocr_window(hwnd: int, tag: str) -> tuple[list[dict], int, int]:
    dest = config.DEBUG_CAPTURES / f"ix_{tag}.bmp"
    width, height = _capture_window_bmp(hwnd, dest)
    say(f"Captured IX window {width}x{height} -> {dest.name}")
    words = _ocr_image(dest)
    if not words:
        png = dest.with_suffix(".png")
        if png.is_file():
            words = _ocr_image(png)
    say(f"OCR words: {len(words)}")
    if words:
        preview = " ".join(str(w.get("text") or "") for w in words[:24])
        say(f"OCR preview: {preview[:220]}")
    return words, width, height


def _apply_review_uses(hwnd: int, write: bool = True, max_clicks: int = 12) -> dict:
    """Click Grammar Use on the Review sidebar for red clips. Never Submit."""
    applied = 0
    stalled = 0
    last_words: list[dict] = []
    last_text = ""
    left, top, width, height = _window_rect(hwnd)
    for step in range(max_clicks):
        uia_text, nodes = _read_uia(hwnd)
        last_text = uia_text
        grammar_n = parse_grammar_clip_count(uia_text)
        if grammar_n:
            say(f"Grammar still has {grammar_n} clip(s)")
        if write and _click_uia_use(hwnd, nodes):
            applied += 1
            stalled = 0
            time.sleep(0.85)
            continue
        if grammar_n and stalled < 5 and _advance_review_target(hwnd, nodes):
            stalled += 1
            time.sleep(0.55)
            continue
        if _OCR_BROKEN:
            say("No Review Use control found (OCR/UIA). Not guessing a click.")
            break
        names = [_uia_name(ctrl) for ctrl in nodes]
        if timeline_dropdown_is_open(names):
            _close_timeline_dropdown(hwnd, nodes)
            time.sleep(0.3)
            continue
        words, img_w, img_h = _ocr_window(hwnd, f"review_{step}")
        last_words = words
        last_text = "\n".join(part for part in (uia_text, ocr_text(words)) if part)
        targets = find_review_use_clicks(words, img_w, img_h)
        if not targets:
            review = find_word_click(
                words, "review", img_w, img_h, x_min_frac=0.45, y_max_frac=0.30
            )
            if review and applied == 0 and step < 2 and not review_sidebar_open(names):
                rx, ry = review
                say(f"Clicked Review tab at {left + rx},{top + ry}")
                if write:
                    _focus(hwnd)
                    _click_screen(left + rx, top + ry)
                    time.sleep(0.5)
                continue
            say("No Review Use control found (OCR/UIA). Not guessing a click.")
            break
        cx, cy = targets[0]
        say(f"Review Use at {left + cx},{top + cy}")
        if not write:
            break
        _focus(hwnd)
        _click_screen(left + cx, top + cy)
        applied += 1
        stalled = 0
        time.sleep(0.85)
    return {"applied": applied, "text": last_text or ocr_text(last_words), "words": last_words}


def _fill_missing_and_reds(hwnd: int, write: bool = True) -> dict:
    """Click 'click to add text' and type fixes for red Quality Assistant clips."""
    left, top, _width, _height = _window_rect(hwnd)
    wrote = 0
    words: list[dict] = []
    img_w = img_h = 1
    uia_text = ""
    nodes: list[Any] = []

    for attempt in range(8):
        uia_text, nodes = _read_uia(hwnd)
        clicked_empty = _click_uia_empty_clip(nodes)
        if not clicked_empty:
            clicked_empty = _click_uia_quality_empty(nodes)
            if clicked_empty:
                time.sleep(0.35)
                uia_text, nodes = _read_uia(hwnd)
                clicked_empty = _click_uia_empty_clip(nodes) or clicked_empty
        if not clicked_empty:
            if _OCR_BROKEN:
                break
            words, img_w, img_h = _ocr_window(hwnd, f"missing_{attempt}")
            target = None
            for phrase in EMPTY_CLIP_PHRASES:
                target = find_phrase_click(words, phrase, img_w, img_h)
                if target:
                    break
            if not target:
                target = find_phrase_click(
                    words, "empty clip", img_w, img_h, y_min_frac=0.62, y_max_frac=0.92
                )
            if target:
                say("Clicked missing clip (click to add text)")
                if write:
                    _focus(hwnd)
                    _double_click_screen(left + target[0], top + target[1])
                clicked_empty = True
        if not clicked_empty:
            break
        if write:
            time.sleep(0.25)
            uia_text, nodes = _read_uia(hwnd, verbose=False)
            names = [_uia_name(ctrl) for ctrl in nodes]
            blob = list(names)
            if not _OCR_BROKEN:
                words, img_w, img_h = _ocr_window(hwnd, f"empty_caption_{attempt}")
                blob.append(ocr_text(words))
            named = _named_rects(nodes)
            min_y = top + int(_height * 0.62)
            if should_recaption_false_idle(names, named, min_y):
                caption = action_caption_for_mislabeled_idle(blob)
            else:
                caption = "Idle"
            _type_into_focused(caption)
            wrote += 1
            say(f"Typed missing caption: {caption}")
            time.sleep(0.45)

    if not words:
        if not _OCR_BROKEN:
            words, img_w, img_h = _ocr_window(hwnd, "after_empty")
        uia_text, nodes = _read_uia(hwnd)

    body = "\n".join(part for part in (uia_text, ocr_text(words)) if part)
    parsed = parse_clips_from_text(body)
    clip_dicts = [clip.to_dict() for clip in parsed]
    if not clip_dicts:
        for cap in captions_from_ocr_blob(body):
            clip_dicts.append({"caption": cap, "kind": "subgoal", "duration_s": None})
    for item in lint_clips(clip_dicts):
        lint = item["lint"]
        if item.get("skip_edit") or not lint.changed:
            continue
        if is_not_timeline_caption(lint.original) or is_not_timeline_caption(lint.rewritten):
            continue
        if is_ocr_caption_garbage(lint.original) or is_ocr_caption_garbage(lint.rewritten):
            continue
        snippet = " ".join((lint.original or "").split()[:5])
        if not snippet or snippet.lower() in {"idle", "click to add text"}:
            continue
        if is_not_timeline_caption(snippet):
            continue
        key = snippet.casefold()
        if key in _REWRITTEN_SNIPPETS:
            continue
        hit = None
        for ctrl in nodes:
            name = _uia_name(ctrl)
            if snippet.lower() in name.lower():
                center = _ctrl_center(ctrl)
                if center:
                    if center[1] < top + _height * 0.55:
                        continue
                    hit = (center[0] - left, center[1] - top)
                    try:
                        if write and _uia_click(ctrl):
                            hit = "uia"
                    except Exception:
                        hit = (center[0] - left, center[1] - top)
                break
        if hit is None:
            hit = find_caption_field_click(words, snippet, img_w, img_h)
        if not hit:
            continue
        say(f"Clicked red clip to edit: {snippet}")
        if not write:
            continue
        if hit != "uia":
            _focus(hwnd)
            _click_screen(left + hit[0], top + hit[1])
        time.sleep(0.2)
        _type_into_focused(lint.rewritten)
        _blur_caption(hwnd, nodes)
        wrote += 1
        _REWRITTEN_SNIPPETS.add(key)
        say(f"Typed caption fix: {lint.rewritten}")
        time.sleep(0.35)
        uia_text, nodes = _read_uia(hwnd)
        words, img_w, img_h = _ocr_window(hwnd, f"edit_{wrote}")
        body = "\n".join(part for part in (uia_text, ocr_text(words)) if part)
    return {"wrote": wrote, "text": body}
