"""Build and lint L1/L2/L3 captions. No LLM. Site Generate-with-AI is a template fill."""

from __future__ import annotations

import re

from .guidelines import (
    ARTICLE_START,
    BANNED_CAPTION_WORDS,
    GERUND_START,
    JUNK_RE,
    L1_MAX,
    L1_MIN_WORDS,
    L2_MAX,
    L2_MIN_WORDS,
    L3_MAX,
    L3_MIN_WORDS,
    PAST_START,
    REPEAT_WORD_RE,
    SKIP_TARGET_ACTIONS,
    URL_RE,
    word_count,
)

HAND_PHRASE = {
    "left_only": "with the left hand",
    "right_only": "with the right hand",
    "both_same": "with both hands",
    "no_hand": "",
    "transfer": "from one hand to the other",
}


def us_keyboard_text(text: str) -> str:
    out = text or ""
    for src, dst in (
        ("\u2018", "'"),
        ("\u2019", "'"),
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u2013", "-"),
        ("\u2014", "-"),
        ("\u00a0", " "),
    ):
        out = out.replace(src, dst)
    return out


def normalize_caption(text: str) -> str:
    blob = us_keyboard_text(text or "")
    blob = blob.replace("gripper", "hand").replace("Grippers", "hands").replace("grippers", "hands")
    blob = re.sub(r"\s+", " ", blob).strip()
    blob = blob.rstrip(" .")
    blob = blob.casefold()
    blob = re.sub(r"\brobot\b", "", blob)
    blob = re.sub(r"\b(?:the )?(?:person|man|woman)\b", "", blob)
    blob = re.sub(r"\s+", " ", blob).strip()
    return blob


def hand_phrase(hand: str) -> str:
    return HAND_PHRASE.get(hand, "with the right hand")


def skip_target(action: str) -> bool:
    return (action or "").casefold() in SKIP_TARGET_ACTIONS


def l3_caption(
    *,
    action: str,
    obj: str,
    target: str | None,
    hand: str,
    left_action: str = "",
    left_object: str = "",
    right_action: str = "",
    right_object: str = "",
    tool: str = "",
) -> str:
    if hand == "both_diff":
        left = _clause(left_action or action, left_object or obj, None, "left_only", tool="")
        right = _clause(right_action or action, right_object or obj, target, "right_only", tool=tool)
        return normalize_caption(f"{left}, and {right}")
    if hand == "no_hand":
        return normalize_caption(_clause(action, obj, target, "no_hand", tool=tool))
    return normalize_caption(_clause(action, obj, target, hand, tool=tool))


def _clause(action: str, obj: str, target: str | None, hand: str, *, tool: str) -> str:
    verb = (action or "move").strip().casefold()
    if verb == "pick":
        verb = "pick up"
    object_bit = " ".join((obj or "the object").split())
    if tool and tool.casefold() not in object_bit.casefold():
        object_bit = f"{object_bit} with {tool}"
    parts = [verb, object_bit]
    if target and not skip_target(action):
        dest = target.strip()
        if not dest.casefold().startswith(("in ", "on ", "onto ", "into ", "to ", "from ")):
            dest = f"in {dest}"
        parts.append(dest)
    phrase = hand_phrase(hand)
    if phrase and hand != "no_hand":
        parts.append(phrase)
    return " ".join(parts)


def l2_caption(*, verb: str, obj: str, target: str | None, extra: str = "") -> str:
    """Object-centric. Never name a hand."""
    action = (verb or "move").strip().casefold()
    if action == "pick":
        action = "pick up"
    object_bit = " ".join((obj or "the object").split())
    parts = [action, object_bit]
    if extra:
        parts = [extra.strip()]
    elif target and not skip_target(verb):
        dest = target.strip()
        if action in {"pick up", "hold", "inspect"}:
            pass
        else:
            if not dest.casefold().startswith(("in ", "on ", "onto ", "into ", "to ", "from ")):
                dest = f"to {dest}"
            parts.append(dest)
    text = normalize_caption(" ".join(parts))
    text = re.sub(r"\bwith the (?:left|right) hand\b", "", text)
    text = re.sub(r"\bwith both hands\b", "", text)
    return normalize_caption(text)


def l1_caption(summary: str) -> str:
    text = normalize_caption(summary)
    if ARTICLE_START.match(text):
        text = "complete " + text
    return text[:L1_MAX].rstrip()


def captions_too_similar(items: list[str], *, min_unique_ratio: float = 0.6) -> bool:
    """Submit blocks nearly identical captions across blocks."""
    cleaned = [normalize_caption(item) for item in items if item]
    if len(cleaned) < 3:
        return False
    unique = {item for item in cleaned}
    return len(unique) / len(cleaned) < min_unique_ratio


def lint_caption(level: str, text: str, *, idle: bool = False) -> str:
    """Empty string means OK. Otherwise a human-readable issue."""
    if idle:
        if text.strip():
            return "Idle spans must not have a caption"
        return ""
    blob = (text or "").strip()
    if not blob:
        return f"{level} caption is blank"
    if blob != blob.casefold():
        return f"{level} caption must be all lowercase"
    if blob.endswith("."):
        return f"{level} caption must not end with a period"
    if URL_RE.search(blob) or JUNK_RE.search(blob) or REPEAT_WORD_RE.search(blob):
        return f"{level} caption has junk or repeated words"
    lowered = f" {blob} "
    if any(word in lowered or word.strip() in blob for word in BANNED_CAPTION_WORDS):
        if "gripper" in blob or "robot" in blob or "the person" in blob:
            return f"{level} caption must say hand, never gripper/robot/person"
    if GERUND_START.match(blob) or PAST_START.match(blob) or ARTICLE_START.match(blob):
        return f"{level} caption must start with an action verb"
    words = word_count(blob)
    if level == "L1":
        if words < L1_MIN_WORDS:
            return "L1 needs at least 2 words"
        if len(blob) > L1_MAX:
            return "L1 is over 180 characters"
        if "hand" in blob:
            return "L1 must not name a hand"
    elif level == "L2":
        if words < L2_MIN_WORDS:
            return "L2 needs at least 5 words"
        if len(blob) > L2_MAX:
            return "L2 is over 300 characters"
        if re.search(r"\b(?:left|right) hand\b", blob) or "both hands" in blob:
            return "L2 must not name a hand"
    else:
        if words < L3_MIN_WORDS:
            return "L3 needs at least 5 words"
        if len(blob) > L3_MAX:
            return "L3 is over 400 characters"
        if ", then " in blob or (blob.startswith("pick") and " and place " in blob):
            return "L3 must be one atomic action, not pick-and-place"
    return ""
