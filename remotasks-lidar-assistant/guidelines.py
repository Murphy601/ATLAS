"""EGO onboarding spec — clipping + captioning rules the engine must follow.

Source: project PDFs (clipping, captioning, clip/caption review, grammar cheat sheet,
forbidden subgoal vocabulary). This module is the machine-readable source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Duration / coverage (Part 1 clipping + review summaries) ---
SUBGOAL_MAX_SECONDS = 9.99  # 9.9s is fine; 10s is not
SUBGOAL_TYPICAL_MIN = 2.0
SUBGOAL_TYPICAL_MAX = 5.0
CLIP_EXPORT_MAX_SECONDS = 5 * 60
IDLE_ISOLATE_SECONDS = 5.0
MID_TASK_COLLECTOR_ISSUE_MIN_SECONDS = 5.0
MAX_ACTIONS_PER_SUBGOAL = 3
FRAME_ALLOWANCE = 5
MAX_IDENTICAL_CAPTIONS = 3

# --- Hard operational constraints ---
WATCH_ENTIRE_VIDEO_FIRST = True
NEVER_CREATE_OR_EDIT_HTE = True
NEVER_LAUNCH_BROWSER = True
NEVER_SUBMIT_BY_DEFAULT = True
REJECT_ONLY_IF_ABSOLUTELY_NECESSARY = True

# --- Banned subgoal vocabulary (forbidden-words sheet + caption review) ---
BANNED_PHRASES = (
    "reach for",
    "fine tune",
    "fine-tune",
)

BANNED_VERBS = frozenset(
    {
        "analyze",
        "assess",
        "browse",
        "check",
        "choose",
        "compare",
        "confirm",
        "count",
        "detail",
        "disengage",
        "ensure",
        "examine",
        "finesse",
        "group",
        "survey",
        "test",
        "tune",
        "verify",
        "view",
        "weigh",
        "inspect",
        "look",
        "match",
        "measure",
        "monitor",
        "observe",
        "organize",
        "portion",
        "prepare",
        "refine",
        "review",
        "rummage",
        "search",
        "select",
        "begin",
        "complete",
        "continue",
        "finalize",
        "initiate",
        "finish",
        "maintain",
        "rearrange",
        "start",
        "adjust",
        "assemble",
        "fix",
        "manipulate",
        "pace",
        "perform",
        "section",
        "work",
        "retrieve",
        "unhang",
        "handle",
    }
)

BANNED_ADJECTIVES = frozenset(
    {
        "additional",
        "again",
        "another",
        "current",
        "extra",
        "final",
        "further",
        "more",
        "new",
        "old",
        "other",
        "remaining",
        "specific",
        "first",
    }
)

BANNED_BRANDS = frozenset({"ipad", "airpods", "iphone", "macbook"})

# Idle / collector-issue labels that need no manipulation caption
NO_DESCRIPTION_NEEDED = frozenset({"idle", "inactive time", "return to home"})

# Precise verb families from the spec
HOLD_VERBS = ("grasp", "grip", "pinch", "hold")
RELEASE_VERBS = ("put", "drop", "set down", "place")
TURN_VERBS = ("twist", "rotate", "turn", "screw")
PREFERRED_PICK = ("pick up", "grasp", "grip", "pinch")

# Preposition cheat sheet
PICK_SOURCE_PREPOSITION = "from"  # pick up / remove X from location
PUT_SURFACE_PREPOSITION = "on"  # static contact
PUT_ENTRY_PREPOSITION = "into"
PUT_ONTO_PREPOSITION = "onto"
WIPE_INSTRUMENT_PREPOSITION = "with"
MOVE_PREPOSITION = "to"

BAD_VIDEO_REASONS = (
    "Personal Information",
    "Toxic Content",
    "Video speed is slow",
    "Useless data",
    "Insufficient progress/incomplete demonstration",
    "Environment (too dark or too bright)",
    "Sensor Issue (pixelation, glares, freezing, blurry footage)",
    "Other",
)

TIMELINES = {
    "collector_issue": "green",
    "clip_export": "red",
    "subgoal": "yellow",
    "hand_tracking_error": "blue",
}

TASK_READY_MARKERS = (
    "Focused Timeline",
    "click or press K to create",
    "ego_rectified_canonical",
    "Sub-goal",
    "Full Timeline",
)


@dataclass(frozen=True)
class DurationVerdict:
    ok: bool
    code: str
    message: str


def subgoal_duration_ok(seconds: float) -> DurationVerdict:
    if seconds >= 10:
        return DurationVerdict(False, "subgoal_too_long", "Subgoal must be < 10s (9.9s is fine, 10s is not)")
    return DurationVerdict(True, "ok", "duration within spec")


def clip_export_duration_ok(seconds: float) -> DurationVerdict:
    if seconds > CLIP_EXPORT_MAX_SECONDS:
        return DurationVerdict(False, "clip_export_too_long", "Clip Export must be < 5 minutes; split longer tasks")
    return DurationVerdict(True, "ok", "duration within spec")


def idle_policy(seconds: float) -> str:
    """How to treat a non-progress pause."""
    if seconds > 10:
        return "split_idle"  # multiple idle subgoals each < 10s
    if seconds > IDLE_ISOLATE_SECONDS:
        return "idle_own_clip"
    return "fold_into_next"


def mid_task_collector_issue_ok(seconds: float) -> bool:
    return seconds > MID_TASK_COLLECTOR_ISSUE_MIN_SECONDS
