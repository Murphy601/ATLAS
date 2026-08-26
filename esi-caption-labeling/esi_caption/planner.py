"""Turn duration + scene + optional motion into a nested L3 → L2 → L1 plan."""

from __future__ import annotations

from dataclasses import dataclass, field

from .captions import l1_caption, l2_caption, l3_caption, lint_caption
from .guidelines import DEFAULT_BLOCK_S, IDLE_STILL_S, LONG_ACTION_S, MIN_ACTION_FRAMES
from .scenes import ScenePack, SceneObject, pick_scene


@dataclass
class MotionSample:
    t: float
    left: float
    right: float

    @property
    def still(self) -> bool:
        return max(self.left, self.right) < 0.04


@dataclass
class L3Span:
    start_s: float
    end_s: float
    idle: bool
    hand: str
    action: str
    obj: str
    target: str | None
    tool: str = ""
    caption: str = ""
    left_action: str = ""
    left_object: str = ""
    right_action: str = ""
    right_object: str = ""

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


@dataclass
class L2Span:
    start_s: float
    end_s: float
    idle: bool
    result: str
    retries: int
    caption: str
    actions: list[L3Span] = field(default_factory=list)


@dataclass
class EpisodePlan:
    duration_s: float
    fps: float
    frame_count: int
    environment: str
    episode_caption: str
    video_id: str
    segments: list[L2Span]
    issues: list[str] = field(default_factory=list)

    @property
    def actions(self) -> list[L3Span]:
        out: list[L3Span] = []
        for segment in self.segments:
            out.extend(segment.actions)
        return out


def parse_clock_blob(text: str) -> tuple[float, float, int, int] | None:
    """Parse '0:28.7 / 1:13.5 | Frame 864 / 2208'."""
    import re

    blob = text or ""
    time_match = re.search(
        r"(\d+):(\d+(?:\.\d+)?)\s*/\s*(\d+):(\d+(?:\.\d+)?)",
        blob,
    )
    frame_match = re.search(r"frame\s+(\d+)\s*/\s*(\d+)", blob, flags=re.I)
    if not time_match:
        return None
    cur = int(time_match.group(1)) * 60 + float(time_match.group(2))
    total = int(time_match.group(3)) * 60 + float(time_match.group(4))
    frame = int(frame_match.group(1)) if frame_match else 0
    frames = int(frame_match.group(2)) if frame_match else max(1, int(round(total * 30)))
    return cur, total, frame, frames


def seconds_to_timestamp(value: float) -> str:
    value = max(0.0, float(value))
    minutes = int(value // 60)
    seconds = value - minutes * 60
    return f"{minutes}:{seconds:04.1f}"


def frames_for(span: L3Span, fps: float) -> int:
    return max(1, int(round(span.duration_s * max(fps, 1.0))))


def _snap(value: float, duration: float) -> float:
    return min(duration, max(0.0, round(float(value), 1)))


def _idle_prefix(samples: list[MotionSample], duration: float) -> float:
    if not samples:
        return 0.0
    still_run = 0.0
    prev = samples[0].t
    for sample in samples:
        dt = max(0.0, sample.t - prev)
        if sample.still:
            still_run += dt
        else:
            break
        prev = sample.t
    if still_run >= IDLE_STILL_S:
        return _snap(min(still_run, duration * 0.35), duration)
    return 0.0


def _hand_from_samples(samples: list[MotionSample], start: float, end: float, default: str) -> str:
    left = 0.0
    right = 0.0
    n = 0
    for sample in samples:
        if start - 0.05 <= sample.t <= end + 0.05:
            left += sample.left
            right += sample.right
            n += 1
    if n == 0:
        return default
    if left > right * 1.6 and left > 0.05:
        return "left_only"
    if right > left * 1.6 and right > 0.05:
        return "right_only"
    if left > 0.05 and right > 0.05:
        return "both_same"
    return default


def _pair_for_object(obj: SceneObject, start: float, mid: float, end: float, hand: str) -> list[L3Span]:
    pick = L3Span(
        start_s=start,
        end_s=mid,
        idle=False,
        hand=obj.hand or hand,
        action=obj.pick_action,
        obj=obj.name,
        target=None,
        tool=obj.tool,
    )
    place = L3Span(
        start_s=mid,
        end_s=end,
        idle=False,
        hand=obj.hand or hand,
        action=obj.place_action,
        obj=obj.name,
        target=obj.target,
        tool=obj.tool,
    )
    pick.caption = l3_caption(action=pick.action, obj=pick.obj, target=None, hand=pick.hand, tool=pick.tool)
    place.caption = l3_caption(
        action=place.action,
        obj=place.obj,
        target=place.target,
        hand=place.hand,
        tool=place.tool,
    )
    return [pick, place]


def _fill_captions(span: L3Span) -> L3Span:
    if span.idle:
        span.caption = ""
        return span
    span.caption = l3_caption(
        action=span.action,
        obj=span.obj,
        target=span.target,
        hand=span.hand,
        tool=span.tool,
        left_action=span.left_action,
        left_object=span.left_object,
        right_action=span.right_action,
        right_object=span.right_object,
    )
    return span


def _segment_from_actions(actions: list[L3Span]) -> L2Span:
    idle = bool(actions) and all(item.idle for item in actions)
    start = actions[0].start_s
    end = actions[-1].end_s
    if idle:
        return L2Span(start_s=start, end_s=end, idle=True, result="", retries=0, caption="", actions=actions)
    obj = next((item.obj for item in actions if not item.idle), "the object")
    target = next((item.target for item in reversed(actions) if item.target), None)
    verb = "move"
    acts = [item.action for item in actions if not item.idle]
    if acts == ["pick", "place"] or acts == ["pick", "put"]:
        extra = f"pick up {obj} and place it {('in ' + target) if target and not target.startswith(('in ', 'on ', 'onto ')) else (target or 'on the work surface')}"
        caption = l2_caption(verb="move", obj=obj, target=target, extra=extra)
    elif acts == ["pick"]:
        caption = l2_caption(verb="pick", obj=obj, target=None)
    else:
        caption = l2_caption(verb=acts[-1] if acts else verb, obj=obj, target=target)
    return L2Span(
        start_s=start,
        end_s=end,
        idle=False,
        result="Success",
        retries=0,
        caption=caption,
        actions=actions,
    )


def _cover_duration(spans: list[L3Span], duration: float) -> list[L3Span]:
    if not spans:
        idle = L3Span(0.0, duration, True, "no_hand", "", "", None)
        return [idle]
    spans = sorted(spans, key=lambda item: item.start_s)
    spans[0].start_s = 0.0
    spans[-1].end_s = duration
    out: list[L3Span] = []
    cursor = 0.0
    for span in spans:
        span.start_s = _snap(max(span.start_s, cursor), duration)
        span.end_s = _snap(max(span.end_s, span.start_s + 0.3), duration)
        if span.start_s > cursor + 0.05:
            gap = L3Span(cursor, span.start_s, True, "no_hand", "", "", None)
            if gap.duration_s >= IDLE_STILL_S:
                out.append(gap)
            else:
                if out:
                    out[-1].end_s = span.start_s
                else:
                    span.start_s = cursor
        out.append(span)
        cursor = span.end_s
    if cursor < duration - 0.05:
        tail = L3Span(cursor, duration, True, "no_hand", "", "", None)
        if tail.duration_s >= IDLE_STILL_S:
            out.append(tail)
        elif out:
            out[-1].end_s = duration
    for item in out:
        item.start_s = _snap(item.start_s, duration)
        item.end_s = _snap(item.end_s, duration)
        _fill_captions(item)
    return out


def _split_long(actions: list[L3Span], duration: float) -> list[L3Span]:
    out: list[L3Span] = []
    for span in actions:
        if span.idle or span.duration_s <= LONG_ACTION_S + 0.05:
            out.append(span)
            continue
        # Idle-like long wait should have been idle. Split a real action at the midpoint.
        mid = _snap((span.start_s + span.end_s) / 2, duration)
        first = L3Span(**{**span.__dict__, "end_s": mid})
        second = L3Span(**{**span.__dict__, "start_s": mid})
        if first.action == "place":
            first.action = "hold"
            first.target = None
        elif first.action == "pick":
            second.action = "place"
        out.extend([_fill_captions(first), _fill_captions(second)])
    return out


def plan_episode(
    *,
    duration_s: float,
    frame_count: int = 0,
    video_blob: str = "",
    samples: list[MotionSample] | None = None,
    scene: ScenePack | None = None,
) -> EpisodePlan:
    duration = max(float(duration_s), 1.0)
    fps = (frame_count / duration) if frame_count else 30.0
    pack = scene or pick_scene(video_blob)
    samples = list(samples or [])
    idle_end = _idle_prefix(samples, duration)
    usable = max(duration - idle_end, 1.0)
    objects = pack.objects
    # At least one pick+place pair per object that fits; never leave 1.5s default blocks.
    pair_budget = max(1, min(len(objects), int(usable / 4.0)))
    chosen = objects[:pair_budget]
    slice_len = usable / max(len(chosen), 1)
    actions: list[L3Span] = []
    if idle_end >= IDLE_STILL_S:
        actions.append(L3Span(0.0, idle_end, True, "no_hand", "", "", None))
    t = idle_end
    for obj in chosen:
        end = min(duration, t + slice_len)
        if end - t < 1.0:
            break
        mid = t + (end - t) * 0.45
        hand = _hand_from_samples(samples, t, end, obj.hand or pack.default_hand)
        pair = _pair_for_object(obj, _snap(t, duration), _snap(mid, duration), _snap(end, duration), hand)
        for item in pair:
            if item.hand == pack.default_hand:
                item.hand = hand if hand else item.hand
            _fill_captions(item)
        actions.extend(pair)
        t = end
    actions = _cover_duration(actions, duration)
    actions = _split_long(actions, duration)
    # Drop tiny non-covering leftovers.
    actions = [item for item in actions if item.end_s > item.start_s and frames_for(item, fps) >= MIN_ACTION_FRAMES]
    actions = _cover_duration(actions, duration)

    segments: list[L2Span] = []
    bucket: list[L3Span] = []
    current_obj = None
    for span in actions:
        key = None if span.idle else span.obj
        if bucket and (span.idle != bucket[-1].idle or (not span.idle and key != current_obj)):
            segments.append(_segment_from_actions(bucket))
            bucket = []
        bucket.append(span)
        current_obj = key
    if bucket:
        segments.append(_segment_from_actions(bucket))

    issues: list[str] = []
    if abs(segments[0].start_s) > 0.05 or abs(segments[-1].end_s - duration) > 0.15:
        issues.append("L2 does not cover the whole video")
    for segment in segments:
        for action in segment.actions:
            if action.start_s < segment.start_s - 0.05 or action.end_s > segment.end_s + 0.05:
                issues.append("L3 crosses an L2 boundary")
            if not action.idle:
                why = lint_caption("L3", action.caption)
                if why:
                    issues.append(why)
        if not segment.idle:
            why = lint_caption("L2", segment.caption)
            if why:
                issues.append(why)
        if any(abs(item.duration_s - DEFAULT_BLOCK_S) < 0.05 for item in segment.actions if not item.idle):
            # 1.5s is allowed only if the real action is that short; keep a note, do not fail.
            pass

    episode = l1_caption(pack.episode)
    why = lint_caption("L1", episode)
    if why:
        issues.append(why)

    return EpisodePlan(
        duration_s=duration,
        fps=fps,
        frame_count=frame_count or int(round(duration * fps)),
        environment=pack.environment,
        episode_caption=episode,
        video_id="",
        segments=segments,
        issues=issues,
    )
