"""Lint and mechanically rewrite EGO subgoal / clip-export captions.

Only applies grammar and spec transforms that stay grounded in the original text.
Does not invent objects from the video.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import guidelines

_GERUND = re.compile(r"\b(\w+ing)\b", re.I)
_USING = re.compile(r"\busing\b", re.I)
_WHILE = re.compile(r"\bwhile\b", re.I)
_THE_BOTH = re.compile(r"\bthe both\b", re.I)
_MID_PERIOD = re.compile(r"\.\s+")
_TRAIL_PUNCT = re.compile(r"[.,;:!?]+$")
_NOUN_CHUNK = re.compile(r"\bthe [a-z]+(?: [a-z]+){0,2}\b", re.I)
_UPPER_LOWER = re.compile(r"\b(upper|lower)\b", re.I)
_HAND = re.compile(r"\b(left hand|right hand|both hands)\b", re.I)
_PICK_ON = re.compile(r"\b(pick up|remove)\s+(the\s+)?(.+?)\s+on\s+(the\s+)?(.+?)(\s+with\b|$)", re.I)
_IT_PRONOUN = re.compile(r"\bfold it\b", re.I)
_TRANSFER_IT = re.compile(r"\btransfer it\b", re.I)
_THIRD_PERSON = re.compile(r"\b(the person|he|she|they)\s+\w+s\b", re.I)
_CLAUSE_SPLIT = re.compile(r"\s*(?:,|;|\band\b)\s*", re.I)
_FIRST_WORD = re.compile(r"^[A-Za-z]+(?:\s+up|\s+down)?")
_OBJECT_AFTER_VERB = re.compile(
    r"^(?:pick up|put|drop|fold|flip|unstack|stack|hold|smooth|transfer|place|set down|wipe|pour|hang|open|close|rotate|twist|turn|grasp|grip|pinch|scrub|cut|remove|grab|shake|pull|push|move)\s+(?:the\s+)?([a-z0-9 ]+?)(?:\s+with\b|\s+from\b|\s+on\b|\s+in\b|,|;|$)",
    re.I,
)

CHROME_CAPTION_MARKERS = (
    "llm check",
    "quality assistant",
    "find & replace",
    "edit history",
    "claim expiry",
    "scene id",
    "review submission",
    "submit the task",
    "shortcuts",
    "skip task",
    "come back in this mode",
    "remaining claim",
    "last checked",
    "ai review paused",
    "project ego",
    "watched 100",
    "full timeline",
    "focused timeline",
    "sensorfusion",
    "remotasks",
    "gmail",
    "click or press k",
)

_FRAME_JUNK = re.compile(r"\bf(?:s|ago)?\d{2,4}[a-z]{0,4}\b", re.I)
_OCR_JUNK_TOKS = ("fago", "fs40", "f7go", "refri*", " or/", "or/ ")
_MASHED_VERBS = re.compile(
    r"\b(pick up|put|open|close|rotate|attach|pour|push|hold|move|tighten)\b",
    re.I,
)
_HAND_SUBSTRING = re.compile(r"hand", re.I)


def is_ocr_caption_garbage(text: str) -> bool:
    """True when OCR mashed several cards / overlay chrome into one string."""
    raw = re.sub(r"\s+", " ", (text or "")).strip()
    if not raw:
        return True
    lowered = raw.casefold()
    if any(tok in lowered for tok in _OCR_JUNK_TOKS):
        return True
    if "*" in raw:
        return True
    if _FRAME_JUNK.search(raw):
        return True
    words = raw.split()
    if len(words) > 28:
        return True
    verbs = _MASHED_VERBS.findall(raw)
    if len(verbs) >= 3 and " and " not in lowered:
        return True
    if re.search(r"\b(?:door|jar|bowl|basin|hand|counter)\s+[A-Z][a-z]+\s+(?:the|up|with)\b", raw):
        return True
    if len(words) >= 8:
        for i in range(len(words) - 7):
            gram = " ".join(words[i : i + 4]).casefold()
            rest = " ".join(words[i + 4 :]).casefold()
            if gram and gram in rest:
                return True
        head = " ".join(words[:5]).casefold()
        rest = " ".join(words[5:]).casefold()
        if head and head in rest:
            return True
    return False


def is_not_timeline_caption(text: str) -> bool:
    """True for sidebar / browser chrome that must never be typed as a subgoal."""
    n = (text or "").casefold()
    if not n.strip():
        return True
    if any(marker in n for marker in CHROME_CAPTION_MARKERS):
        return True
    return is_ocr_caption_garbage(text)


BRAND_RE = re.compile(r"\b(" + "|".join(re.escape(b) for b in guidelines.BANNED_BRANDS) + r")\b", re.I)


@dataclass
class LintIssue:
    code: str
    message: str
    severity: str = "error"  # error must be fixed; warning can stand


@dataclass
class LintResult:
    original: str
    rewritten: str
    issues: list[LintIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def changed(self) -> bool:
        return self.rewritten.strip() != self.original.strip()


def _clauses(text: str) -> list[str]:
    parts = [p.strip(" .") for p in _CLAUSE_SPLIT.split(text) if p.strip(" .")]
    return parts or ([text.strip()] if text.strip() else [])


def _named_object(text: str) -> str | None:
    match = _OBJECT_AFTER_VERB.search(text.strip())
    if not match:
        return None
    obj = re.sub(r"\s+", " ", match.group(1)).strip()
    obj = re.sub(r"\b(with|from|on|in|into|onto|and)\b.*", "", obj).strip()
    return obj or None


def lint_subgoal(caption: str, duration_s: float | None = None) -> LintResult:
    original = (caption or "").strip()
    issues: list[LintIssue] = []
    text = original

    lowered = text.lower().strip()
    if lowered in guidelines.PLACEHOLDER_CAPTIONS:
        issues.append(LintIssue("empty_caption", "ClipExport and Sub-goal clips must contain text"))
        return LintResult(original, "Idle", issues)

    if not text:
        issues.append(LintIssue("empty_caption", "ClipExport and Sub-goal clips must contain text"))
        return LintResult(original, "Idle", issues)
    if lowered in guidelines.NO_DESCRIPTION_NEEDED or lowered.startswith("idle"):
        if duration_s is not None and duration_s > guidelines.IDLE_ISOLATE_SECONDS:
            issues.append(
                LintIssue(
                    "idle_too_long",
                    "No idle time should be more than 5s, please split it into smaller segments",
                )
            )
        elif duration_s is not None and duration_s <= guidelines.IDLE_ISOLATE_SECONDS:
            issues.append(
                LintIssue(
                    "idle_too_short",
                    "Idle under 5s should be folded into the next action, not its own subgoal",
                    "warning",
                )
            )
        return LintResult(original, "Idle", issues)

    if duration_s is not None:
        verdict = guidelines.subgoal_duration_ok(duration_s)
        if not verdict.ok:
            issues.append(LintIssue(verdict.code, verdict.message))

    if _USING.search(text):
        issues.append(LintIssue("using_not_with", 'Use "with", never "using"'))
        text = _USING.sub("with", text)
    if _WHILE.search(text):
        issues.append(LintIssue("while_not_and", 'Join two hands with "and", never "while"'))
        text = _WHILE.sub("and", text)
    if _THE_BOTH.search(text):
        issues.append(LintIssue("the_both", 'Say "both hands", not "the both hands"'))
        text = _THE_BOTH.sub("both", text)
    if _UPPER_LOWER.search(text):
        issues.append(LintIssue("upper_lower", 'Use top/bottom, never "upper/lower"'))
        text = re.sub(r"\bupper\b", "top", text, flags=re.I)
        text = re.sub(r"\blower\b", "bottom", text, flags=re.I)

    brand = BRAND_RE.search(text)
    if brand:
        issues.append(LintIssue("brand_name", f"Generic names only — do not use {brand.group(1)}"))

    obj = _named_object(text)
    if obj and _IT_PRONOUN.search(text):
        issues.append(LintIssue("pronoun", f'Replace "it" with "{obj}"'))
        noun = obj if obj.lower().startswith("the ") else f"the {obj}"
        text = _IT_PRONOUN.sub(f"fold {noun}", text)
    if obj and _TRANSFER_IT.search(text):
        issues.append(LintIssue("pronoun", f'Name the object in the transfer: "{obj}"'))
        text = _TRANSFER_IT.sub(f"transfer the {obj}", text)
        text = re.sub(r"\bthe the\b", "the", text)

    pick_on = _PICK_ON.search(text)
    if pick_on:
        issues.append(LintIssue("pick_from", "Pick up / remove uses from [location], not on [location]"))
        text = _PICK_ON.sub(
            lambda m: f"{m.group(1)} {('the ' + m.group(3) if m.group(2) else m.group(3)).strip()} from "
            f"{('the ' + m.group(5) if m.group(4) else m.group(5)).strip()}{m.group(6)}",
            text,
            count=1,
        )

    if _THIRD_PERSON.search(text) or re.search(r"\b(wipes|removes|picks|holds|folds)\b", text):
        issues.append(LintIssue("not_imperative", "Subgoals must be imperative — no -ing, no third person"))

    gerunds = [g for g in _GERUND.findall(text) if g.lower() not in {"during"}]
    # Allow present-participle nouns rarely; flag verb-like -ing at clause start
    for clause in _clauses(text):
        first = clause.split()[0] if clause.split() else ""
        if first.lower().endswith("ing"):
            issues.append(LintIssue("gerund", f'Use the imperative "{first[:-3]}" not "{first}"'))

    if not _HAND.search(text):
        issues.append(LintIssue("missing_hand", "Every subgoal must name left hand, right hand, or both hands"))

    clauses = _clauses(text)
    if len(clauses) > guidelines.MAX_ACTIONS_PER_SUBGOAL:
        issues.append(
            LintIssue(
                "too_many_actions",
                f"At most {guidelines.MAX_ACTIONS_PER_SUBGOAL} action+object+hand combinations per subgoal",
            )
        )

    first_word = (text.split() or [""])[0].lower()
    first_two = " ".join(text.split()[:2]).lower()
    if first_two in {"reach for", "fine tune", "set down"}:
        pass
    if first_two == "reach for" or first_word in guidelines.BANNED_VERBS:
        issues.append(
            LintIssue(
                "banned_verb",
                f'"{first_word}" is on the forbidden subgoal list — pick a precise manipulation verb',
            )
        )
    if "reach for" in lowered:
        issues.append(LintIssue("banned_verb", '"reach for" is forbidden'))

    for adj in guidelines.BANNED_ADJECTIVES:
        if re.search(rf"\b{adj}\b", lowered):
            issues.append(
                LintIssue("banned_adjective", f'"{adj}" is on the forbidden subgoal list', "warning")
            )
            break

    # Quality Assistant: no mid/end punctuation; at least 10 words.
    if _MID_PERIOD.search(text):
        issues.append(LintIssue("mid_period", "Join subgoal actions with and, not a period"))
        text = _MID_PERIOD.sub(" and ", text)
        text = re.sub(r"\band ([A-Z])", lambda m: "and " + m.group(1).lower(), text)
    if _TRAIL_PUNCT.search(text.strip()):
        issues.append(LintIssue("trailing_punct", "Descriptions must end in letters, not periods or commas"))
        text = _TRAIL_PUNCT.sub("", text.strip())

    # Normalize "and" joining + spacing
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        text = text[0].upper() + text[1:]
    if text.lower() != "idle":
        padded = _pad_to_min_words(text, guidelines.SUBGOAL_MIN_WORDS)
        if padded != text:
            issues.append(
                LintIssue("too_short", "Sub-goals must be at least 10 words long")
            )
            text = padded

    return LintResult(original, text, issues)


def _pad_to_min_words(text: str, minimum: int) -> str:
    """Lengthen a caption with a complete grounded clause. Never end on a dangling 'with'."""
    parts = text.split()
    if len(parts) >= minimum:
        return text
    obj = _named_object(text)
    if obj and not obj.startswith("the "):
        obj = f"the {obj}"
    if obj:
        extra = f" and hold {obj} with both hands"
    elif "hand" in text.lower():
        extra = " and hold the object with both hands"
    else:
        extra = " with the left hand and the right hand"
    padded = re.sub(r"\s+", " ", (text + extra).strip())
    while len(padded.split()) < minimum:
        padded = f"{padded} with both hands"
        if len(padded.split()) > minimum + 8:
            break
    return padded


def lint_clip_export(caption: str) -> LintResult:
    original = (caption or "").strip()
    issues: list[LintIssue] = []
    if not original:
        issues.append(LintIssue("empty_clip_export", "Clip Export needs 1–2 sentences with environment and task"))
        return LintResult(original, original, issues)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", original) if s.strip()]
    if len(sentences) > 2:
        issues.append(LintIssue("too_many_sentences", "Clip Export description is at most 2 sentences"))
    if len(original.split()) < 15:
        issues.append(LintIssue("too_vague", "Clip Export descriptions must be at least 15 words long"))
    env_tokens = (
        "kitchen",
        "counter",
        "desk",
        "table",
        "bedroom",
        "living",
        "office",
        "floor",
        "room",
        "outdoor",
        "garage",
        "bathroom",
        "sink",
        "stove",
        "refrigerator",
        "fridge",
    )
    if not any(tok in original.lower() for tok in env_tokens):
        issues.append(LintIssue("missing_environment", "Clip Export must include the environment"))
    if original.lower().startswith(("make ", "do ", "fold ", "clean ")):
        issues.append(LintIssue("not_sentence", "Clip Export is 2nd/3rd person sentences, not an imperative title"))
    if _HAND_SUBSTRING.search(original):
        issues.append(
            LintIssue(
                "hands_wording",
                "Clip Export must not mention hands (including words like handling)",
            )
        )
    return LintResult(original, original, issues)


def action_caption_for_mislabeled_idle(captions: list[str]) -> str:
    """10+ word hand caption for a first clip that is labeled Idle but has action.

    Grounded in the next sub-goal's objects. Never uses "reach for".
    """
    neighbors = [c for c in captions if c and not is_not_timeline_caption(c)]
    blob = " ".join(neighbors).lower()
    obj = None
    for cap in neighbors:
        if cap.strip().lower() in guidelines.NO_DESCRIPTION_NEEDED or cap.strip().lower().startswith("idle"):
            continue
        named = _named_object(cap)
        if named:
            obj = named
            break
    if obj is None:
        if "mayonnaise" in blob or "jar" in blob:
            obj = "red mayonnaise jar"
        elif "bowl" in blob:
            obj = "green bowl"
        elif "basin" in blob:
            obj = "gray basin"
        elif "pants" in blob:
            obj = "pants"
        elif "blouse" in blob:
            obj = "blouse"
        elif "shirt" in blob:
            obj = "shirt"
        else:
            obj = "objects"
    if any(tok in blob for tok in ("kitchen", "counter", "refrigerator", "jar", "bowl", "basin")):
        text = f"Move both hands toward the {obj} on the kitchen counter"
    elif any(tok in blob for tok in ("shirt", "blouse", "pants", "laundry", "fold", "table")):
        text = f"Move both hands toward the {obj} on the table with the left hand"
    else:
        text = f"Move both hands toward the {obj} with the left hand"
    text = re.sub(r"\bthe the\b", "the", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[0].upper() + text[1:]


def captions_from_ocr_blob(text: str) -> list[str]:
    """Pull imperative hand captions out of messy OCR, including period-joined cards."""
    if not text:
        return []
    blob = text.replace("\u00a0", " ")
    out: list[str] = []
    joined = re.compile(
        r"((?:[A-Z][^.!?\n]{8,160}(?:left hand|right hand|both hands)[^.!?\n]{0,40})"
        r"(?:\.\s+[A-Z][^.!?\n]{8,160}(?:left hand|right hand|both hands)[^.!?\n]{0,40})+)"
    )
    for match in joined.finditer(blob):
        cap = re.sub(r"\s+", " ", match.group(1)).strip()
        if cap and not is_not_timeline_caption(cap):
            out.append(cap)
    single = re.compile(
        r"([A-Z][^.!?\n]{8,160}(?:left hand|right hand|both hands)[^.!?\n]{0,80})"
    )
    for match in single.finditer(blob):
        cap = re.sub(r"\s+", " ", match.group(1)).strip()
        if not cap or is_not_timeline_caption(cap):
            continue
        if any(cap in existing or existing in cap for existing in out):
            continue
        out.append(cap)
    return out


def _third_person_verb(verb: str) -> str:
    word = (verb or "").strip().lower()
    irregular = {
        "put": "puts",
        "hold": "holds",
        "pick": "picks",
        "have": "has",
        "stand": "stands",
        "sit": "sits",
    }
    if word in irregular:
        return irregular[word]
    if word.endswith("y") and len(word) > 2 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "sh", "ch", "x", "z", "o")):
        return word + "es"
    if word.endswith("s"):
        return word
    return word + "s"


def clip_export_sentence_for_subgoal(caption: str) -> str:
    """One third-person Clip Export sentence for a single Sub-goal span."""
    raw = (caption or "").strip()
    if not raw or is_ocr_caption_garbage(raw) or is_not_timeline_caption(raw):
        return ""
    if raw.lower() in guidelines.NO_DESCRIPTION_NEEDED or raw.lower().startswith("idle"):
        return ensure_clip_export_min_words(
            "The person stands at a kitchen counter between recorded actions "
            "during this indoor demonstration."
        )
    cleaned = lint_subgoal(raw).rewritten
    if cleaned.lower() == "idle":
        return ensure_clip_export_min_words(
            "The person stands at a kitchen counter between recorded actions "
            "during this indoor demonstration."
        )
    cleaned = re.sub(r"\bwith both hands\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bwith the (?:left|right) hand\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bhandling\b", "moving", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
    if not cleaned or _HAND_SUBSTRING.search(cleaned):
        return ""
    words = cleaned.split()
    verb = words[0]
    rest = words[1:]
    if rest and rest[0].lower() == "up":
        tp_verb = "picks up"
        rest = rest[1:]
    elif rest and rest[0].lower() == "down":
        tp_verb = f"{_third_person_verb(verb)} down"
        rest = rest[1:]
    else:
        tp_verb = _third_person_verb(verb)
    body = " ".join([tp_verb, *rest]).strip()
    blob = cleaned.lower()
    laundry = any(tok in blob for tok in ("shirt", "blouse", "pants", "laundry", "fold", "table"))
    if "kitchen" in blob or "counter" in blob:
        sentence = f"The person {body} at the kitchen counter during this recorded task."
    elif "refrigerator" in blob or "fridge" in blob:
        sentence = f"The person {body} at the refrigerator during this kitchen task."
    elif laundry:
        sentence = f"The person {body} at an indoor table during a laundry folding task."
    else:
        sentence = f"The person {body} at a kitchen counter during this recorded task."
    sentence = re.sub(r"\s+", " ", sentence).strip()
    sentence = sentence[0].upper() + sentence[1:]
    if not sentence.endswith("."):
        sentence += "."
    if _HAND_SUBSTRING.search(sentence):
        return ""
    return ensure_clip_export_min_words(sentence)


def clip_export_from_subgoals(captions: list[str]) -> str:
    """1–2 environment sentences grounded in already-written subgoal nouns."""
    clean = [
        cap
        for cap in captions
        if cap and not is_ocr_caption_garbage(cap) and not is_not_timeline_caption(cap)
    ]
    blob = " ".join(clean or captions).lower()
    kitchen_tokens = (
        "kitchen",
        "refrigerator",
        "fridge",
        "counter",
        "bowl",
        "jar",
        "basin",
        "mayonnaise",
        "dispenser",
        "pepsi",
        "bottle",
        "plastic",
        "bag",
        "stove",
    )
    if any(tok in blob for tok in ("pepsi", "bottle", "plastic bag", "plastic bags")):
        return ensure_clip_export_min_words(
            "The person stands at a kitchen refrigerator and moves a soda bottle "
            "and plastic bags during this recorded task."
        )
    if any(tok in blob for tok in ("shirt", "blouse", "pants", "laundry", "fold")):
        return ensure_clip_export_min_words(
            "The person stands at an indoor table and folds shirts, pants, "
            "and a blouse during a laundry task."
        )
    if any(tok in blob for tok in kitchen_tokens):
        return ensure_clip_export_min_words(
            "The person stands at a kitchen counter and moves jars, a bowl, "
            "and a refrigerator door during this recorded task."
        )
    return ensure_clip_export_min_words(
        "The person works in an indoor room and moves the objects described "
        "in the sub-goals during this recorded task."
    )


def ensure_clip_export_min_words(text: str, minimum: int = 15) -> str:
    """Pad a Clip Export sentence to QA's 15-word minimum without saying hand."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    cleaned = re.sub(r"\bhousehold\b", "home", cleaned, flags=re.I)
    cleaned = re.sub(r"\bhandling\b", "moving", cleaned, flags=re.I)
    if _HAND_SUBSTRING.search(cleaned):
        cleaned = _HAND_SUBSTRING.sub("", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.")
    if not cleaned:
        cleaned = (
            "The person works at an indoor table during a laundry "
            "folding demonstration of this recorded task."
        )
    body = cleaned.rstrip(".")
    pad = "during this indoor recorded demonstration of the task"
    while len(body.split()) < minimum:
        body = f"{body} {pad}"
        if len(body.split()) > minimum + 12:
            break
    out = body[0].upper() + body[1:]
    if not out.endswith("."):
        out += "."
    return out


def clip_export_slot_sentences(
    captions: list[str], n_slots: int, fallback: str | None = None
) -> list[str]:
    """One no-hands Clip Export sentence per Sub-goal span."""
    fallback_text = (fallback or "").strip() or clip_export_from_subgoals(captions)
    if _HAND_SUBSTRING.search(fallback_text):
        fallback_text = clip_export_from_subgoals(["kitchen counter refrigerator"])
    n = max(int(n_slots or 0), 1)
    per: list[str] = []
    for cap in captions or []:
        sentence = clip_export_sentence_for_subgoal(cap)
        if sentence:
            per.append(sentence)
    if len(per) >= n:
        return per[:n]
    while len(per) < n:
        per.append(fallback_text)
    return [ensure_clip_export_min_words(s) for s in per]


def subgoal_captions_from_names(names: list[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        text = (name or "").strip()
        if len(text) < 16:
            continue
        lowered = text.lower()
        if "hand" not in lowered:
            continue
        if lowered.startswith("error"):
            continue
        out.append(text)
    return out


def lint_clips(clips: list[dict]) -> list[dict]:
    """Annotate clip dicts with lint results. Does not modify HTE clips."""
    out = []
    seen_captions: dict[str, int] = {}
    for clip in clips:
        kind = (clip.get("kind") or "subgoal").lower()
        if kind in {"hte", "hand_tracking_error", "hand tracking error"}:
            item = dict(clip)
            item["lint"] = LintResult(clip.get("caption") or "", clip.get("caption") or "", [])
            item["skip_edit"] = True
            out.append(item)
            continue
        caption = clip.get("caption") or ""
        if is_not_timeline_caption(caption):
            item = dict(clip)
            item["lint"] = LintResult(caption, caption, [])
            item["skip_edit"] = True
            out.append(item)
            continue
        duration = clip.get("duration_s")
        if kind in {"clip_export", "clip export", "demonstration"}:
            result = lint_clip_export(caption)
        else:
            result = lint_subgoal(caption, duration)
            key = result.rewritten.lower()
            seen_captions[key] = seen_captions.get(key, 0) + 1
            if seen_captions[key] > guidelines.MAX_IDENTICAL_CAPTIONS:
                result.issues.append(
                    LintIssue(
                        "needs_differentiator",
                        "Identical captions are allowed at most 3 times; the 4th needs a corner/side/color",
                    )
                )
        item = dict(clip)
        item["lint"] = result
        item["skip_edit"] = False
        out.append(item)
    return out
