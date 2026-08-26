from esi_caption.win_ui import page_is_task, submit_blocked


def test_task_page_detection() -> None:
    assert page_is_task("Hierarchical Egocentric Video Captioning | 0 labeled")
    assert page_is_task("https://www.multimango.com/tasks/vs-1781285808-260612-esi-caption-labeling")
    assert not page_is_task("Inbox - Gmail")


def test_submit_blocked_on_issues() -> None:
    assert submit_blocked("10 issue(s) to fix before you can submit") is True
    assert submit_blocked("Submit Captions (6 segs)") is False
