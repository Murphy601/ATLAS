from browser_engine import LidarBrowser
from ego_task import is_ego_task_text, parse_clips_from_text

SCREENSHOT_TEXT = """
Review  Similar  Find & Replace  Edit history
ego_rectified_canonical
60 FPS (0-62)
Sub-goal
1x
±5f
ego_rectified_canonical
No issues — clips look clean.
Focused Timeline
pending | 1.9s Drop the pants with both hands and fold it with both hands
pending | 3.4s Unstack the blouse with the left hand
| 1.2s Flip the shirt with the right hand
| 1.4s Pick up the pants on the table with the left hand
pending | 4.5s Fold the pants with both hands, fold the shirt with both hands, put the shirt on the table with both hands
pending | 3.9s Smooth the blouse with the left hand, and transfer it to the right hand
click or press K to create
Full Timeline
"""


def test_screenshot_is_detected_as_open_task():
    assert is_ego_task_text(SCREENSHOT_TEXT)


def test_parses_focused_timeline_clips():
    clips = parse_clips_from_text(SCREENSHOT_TEXT)
    assert len(clips) == 6
    assert clips[0].pending is True
    assert clips[0].duration_s == 1.9
    assert "Drop the pants" in clips[0].caption
    assert clips[2].pending is False
    assert clips[2].duration_s == 1.2
    assert all(c.duration_s is not None and c.duration_s < 10 for c in clips)


def test_does_not_launch_browser():
    browser = LidarBrowser()
    try:
        browser.launch()
        raise AssertionError("launch() must not open Chrome")
    except RuntimeError as exc:
        assert "does not open Chrome" in str(exc)


def test_parses_sensorfusionlab_ocr_cards():
    text = """
Focused Timeline
3.3s
Attach the refrigerator door with the both hands
2.8s
Pick up the red mayonnaise jar with the left hand
click or press K to create
Full Timeline
Watched 92%
"""
    clips = parse_clips_from_text(text)
    assert len(clips) >= 2
    assert clips[0].duration_s == 3.3
    assert "refrigerator door" in clips[0].caption
    assert "mayonnaise" in clips[1].caption


def test_parse_clips_ignores_sidebar_chrome() -> None:
    text = """
Focused Timeline
LLM check not yet run. QUALITY ASSISTANT Error All ClipExports
Shortcuts q q fs40 Rotate the jar
pending | 2.7s Pick up the red mayonnaise jar with the left hand
click or press K to create
"""
    clips = parse_clips_from_text(text)
    assert len(clips) == 1
    assert "mayonnaise" in clips[0].caption
    assert all("QUALITY ASSISTANT" not in c.caption for c in clips)
    assert all("Shortcuts" not in c.caption for c in clips)


def test_parses_sensorfusionlab_range_cards() -> None:
    text = """
Focused Timeline
0s - 5.1s (5.1s)
Move both hands toward the red mayonnaise jar on the kitchen counter
edited
5.1s - 8.2s (3.1s)
Pick up the red mayonnaise jar with the left hand
pending
13.9s - 17.0s (3.1s)
Open the refrigerator door with the left hand. Hold the red mayonnaise jar with the left hand and hold the blue container with the right hand
19.8s - 22.0s (2.2s)
Pour the black bucket from the right to the left hand. Put the blue container into the middle layer of the refrigerator with the right hand
click or press K to create
Full Timeline
Watched 100%
"""
    clips = parse_clips_from_text(text)
    assert len(clips) >= 4
    assert clips[0].start_s == 0.0
    assert clips[0].end_s == 5.1
    assert "mayonnaise" in clips[0].caption.lower()
    fridge = [c for c in clips if "refrigerator door" in c.caption.lower()]
    assert fridge
    assert "." in fridge[0].caption
