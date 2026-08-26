"""Hierarchical caption rules from the MultiMango ESI labeling task."""

from __future__ import annotations

import re

TASK_URL = "https://www.multimango.com/tasks/vs-1781285808-260612-esi-caption-labeling"
TASK_HOST = "multimango.com"
TASK_PATH_HINT = "esi-caption-labeling"

ENVIRONMENTS = (
    "Home",
    "Office & Institutional",
    "Retail",
    "Food & Hospitality",
    "Workshop & Repair",
    "Automotive",
    "Manufacturing",
    "Crafts & Fabrication",
    "Outdoor & Agriculture",
    "Sports & Recreation",
)

HAND_OPTIONS = (
    "left_only",
    "right_only",
    "no_hand",
    "both_same",
    "both_diff",
    "transfer",
)

HAND_BUTTONS = {
    "left_only": "Left hand only",
    "right_only": "Right hand only",
    "no_hand": "No hand",
    "both_same": "Both hands same action",
    "both_diff": "Both hands diff actions",
    "transfer": "Transfer between hands",
}

ACTIONS: tuple[str, ...] = (
    "pick",
    "place",
    "put",
    "return",
    "hang",
    "move",
    "slide",
    "align",
    "orient",
    "rotate",
    "flip",
    "transfer",
    "pass",
    "arrange",
    "stack",
    "sort",
    "separate",
    "grasp",
    "pinch",
    "hold",
    "secure",
    "release",
    "drop",
    "insert",
    "attach",
    "connect",
    "assemble",
    "install",
    "fasten",
    "plug",
    "remove",
    "detach",
    "disconnect",
    "unplug",
    "disassemble",
    "open",
    "close",
    "fold",
    "unfold",
    "clean",
    "wipe",
    "wash",
    "scrub",
    "brush",
    "sweep",
    "polish",
    "sand",
    "scrape",
    "paint",
    "spray",
    "cut",
    "trim",
    "slice",
    "chop",
    "peel",
    "tear",
    "drill",
    "grind",
    "file",
    "shape",
    "form",
    "crease",
    "straighten",
    "weave",
    "stamp",
    "press",
    "push",
    "pull",
    "pry",
    "squeeze",
    "bend",
    "hammer",
    "tap",
    "poke",
    "twist",
    "screw",
    "unscrew",
    "roll",
    "coil",
    "fill",
    "empty",
    "pour",
    "dispense",
    "replenish",
    "scoop",
    "inspect",
    "scan",
    "monitor",
    "analyze",
    "assess",
    "test",
    "confirm",
    "measure",
    "weigh",
    "count",
    "collect",
    "organize",
    "label",
    "pack",
    "prepare",
    "operate",
    "activate",
    "interact",
    "walk",
    "drive",
    "lift",
    "lower",
    "gesture",
    "write",
    "mark",
)

SKIP_TARGET_ACTIONS = frozenset(
    {
        "pick",
        "grasp",
        "pinch",
        "hold",
        "secure",
        "inspect",
        "scan",
        "monitor",
        "analyze",
        "assess",
        "test",
        "confirm",
        "measure",
        "weigh",
        "count",
        "release",
    }
)

FORBIDDEN_CLICKS = (
    "skip",
    "flag bad video",
    "flag for removal",
    "flag for",
    "guidelines",
)

NEVER_SUBMIT_WHILE = (
    "issue(s) to fix",
    "issues to fix",
    "cannot submit",
)

L1_MAX = 180
L2_MAX = 300
L3_MAX = 400
L1_MIN_WORDS = 2
L2_MIN_WORDS = 5
L3_MIN_WORDS = 5
MIN_ACTION_FRAMES = 5
LONG_ACTION_S = 8.0
IDLE_STILL_S = 2.0
DEFAULT_BLOCK_S = 1.5

BANNED_CAPTION_WORDS = (
    "gripper",
    "grippers",
    "robot",
    "the person",
    "the man",
    "the woman",
    " he ",
    " she ",
    " his ",
    " her ",
)

GERUND_START = re.compile(r"^(picking|placing|holding|opening|putting|moving)\b", re.I)
PAST_START = re.compile(r"^(picked|placed|held|opened|put|moved)\b", re.I)
ARTICLE_START = re.compile(r"^(the|a|an)\b", re.I)
URL_RE = re.compile(r"https?://|www\.", re.I)
REPEAT_WORD_RE = re.compile(r"\b([a-z]{2,})\s+\1\b", re.I)
JUNK_RE = re.compile(r"[\[\]{}<>]|[|]{2,}|[.]{3,}")


def is_forbidden_click(name: str) -> bool:
    lowered = " ".join((name or "").split()).casefold()
    if not lowered:
        return False
    if lowered in {"skip", "flag bad video", "flag for removal", "guidelines"}:
        return True
    if lowered.startswith("flag for") or lowered.startswith("flag bad"):
        return True
    return False


def word_count(text: str) -> int:
    return len([part for part in re.split(r"\s+", (text or "").strip()) if part])
