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
_UPPER_LOWER = re.compile(r"\b(upper|lower)\b", re.I)
_HAND = re.compile(r"\b(left hand|right hand|both hands)\b", re.I)
_PICK_ON = re.compile(r"\b(pick up|remove)\s+(the\s+)?(.+?)\s+on\s+(the\s+)?(.+?)(\s+with\b|$)", re.I)
_IT_PRONOUN = re.compile(r"\bfold it\b", re.I)
_TRANSFER_IT = re.compile(r"\btransfer it\b", re.I)
_THIRD_PERSON = re.compile(r"\b(the person|he|she|they)\s+\w+s\b", re.I)
_CLAUSE_SPLIT = re.compile(r"\s*(?:,|;|\band\b)\s*", re.I)
_FIRST_WORD = re.compile(r"^[A-Za-z]+(?:\s+up|\s+down)?")
_OBJECT_AFTER_VERB = re.compile(
    r"^(?:pick up|put|drop|fold|flip|unstack|stack|hold|smooth|transfer|place|set down|wipe|pour|hang|open|close|rotate|twist|turn|grasp|grip|pinch|scrub|cut|remove)\s+(?:the\s+)?([a-z0-9 ]+?)(?:\s+with\b|\s+from\b|\s+on\b|\s+in\b|,|;|$)",
    re.I,
)

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

    if not text:
        issues.append(LintIssue("empty_caption", "Every subgoal needs a caption unless it is Idle"))
        return LintResult(original, original, issues)

    lowered = text.lower().strip()
    if lowered in guidelines.NO_DESCRIPTION_NEEDED or lowered.startswith("idle"):
        if duration_s is not None and duration_s <= guidelines.IDLE_ISOLATE_SECONDS:
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

    # Normalize "and" joining + spacing
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        text = text[0].upper() + text[1:]
    if not text.endswith(".") and "the person" not in lowered:
        pass  # subgoals are imperative fragments; no required period

    return LintResult(original, text, issues)


def lint_clip_export(caption: str) -> LintResult:
    original = (caption or "").strip()
    issues: list[LintIssue] = []
    if not original:
        issues.append(LintIssue("empty_clip_export", "Clip Export needs 1–2 sentences with environment and task"))
        return LintResult(original, original, issues)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", original) if s.strip()]
    if len(sentences) > 2:
        issues.append(LintIssue("too_many_sentences", "Clip Export description is at most 2 sentences"))
    if len(original.split()) < 8:
        issues.append(LintIssue("too_vague", 'Clip Export cannot be a short command like "Make a sandwich"'))
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
    )
    if not any(tok in original.lower() for tok in env_tokens):
        issues.append(LintIssue("missing_environment", "Clip Export must include the environment"))
    if original.lower().startswith(("make ", "do ", "fold ", "clean ")):
        issues.append(LintIssue("not_sentence", "Clip Export is 2nd/3rd person sentences, not an imperative title"))
    return LintResult(original, original, issues)


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
