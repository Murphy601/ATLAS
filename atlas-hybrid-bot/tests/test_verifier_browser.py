from pathlib import Path

import config
from browser_automation import VideoBrowserBot
from verifier_logic import (
    decide_clause_verification,
    decide_missing_action,
    infer_rejection_reason,
)

FIXTURE = Path(__file__).parent / "fixtures" / "verifier_portal.html"


def test_decide_clause_verification_accepts_valid_grammar():
    clauses = [
        "hold glass cup with left hand",
        "scrub glass cup with sponge in right hand",
    ]
    assert decide_clause_verification(clauses[0], clauses, index=0)
    assert decide_clause_verification(clauses[1], clauses, index=1)


def test_decide_clause_verification_accepts_related_scoop_clauses():
    """Cooking training clip: clause 3 is valid even without 'into pot'."""
    clauses = [
        "hold container with left hand",
        "scoop food from container into pot with spoon in right hand",
        "scoop food from container with spoon in right hand",
    ]
    expected = [
        "hold container with left hand",
        "scoop food from container into pot with spoon in right hand",
    ]
    for index, clause in enumerate(clauses):
        assert decide_clause_verification(
            clause,
            clauses,
            expected_clauses=expected,
            index=index,
        )


def test_decide_clause_verification_approves_duplicate_scoop():
    clauses = [
        "scoop food from container into pot with spoon in right hand",
        "scoop food from container into pot with spoon in right hand",
    ]
    assert decide_clause_verification(clauses[0], clauses, index=0)
    assert decide_clause_verification(clauses[1], clauses, index=1)


def test_decide_clause_verification_rejects_bad_grammar():
    clauses = ["hold container with left hand", "container left hand hold"]
    assert decide_clause_verification(clauses[0], clauses, index=0)
    assert not decide_clause_verification(clauses[1], clauses, index=1)


def test_infer_rejection_reason_for_bad_grammar():
    clauses = ["hold bottle with right hand", "bottle right hand"]
    reason = infer_rejection_reason(clauses[1], clauses, index=1)
    assert reason == "Grammar / spelling"


def test_infer_rejection_reason_for_exact_duplicate():
    clauses = [
        "scoop food from container into pot with spoon in right hand",
        "scoop food from container into pot with spoon in right hand",
    ]
    reason = infer_rejection_reason(clauses[1], clauses, index=1)
    assert reason == "Added action"


def test_decide_missing_action_defaults_to_no():
    shown = ["hold bottle with right hand"]
    expected = "hold bottle with right hand, pass bottle from right hand to left hand"
    assert not decide_missing_action(shown, expected_label=expected)


def test_open_verifier_training_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ATLAS_LABEL_MODE", "verifier")
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        mode = bot.open_work_queue()
        assert mode == "verifier"
        assert bot.is_verifier_exercise()
        clauses = bot.discover_verifier_clauses()
        assert len(clauses) == 2
        assert clauses[0].text.lower() == "hold glass cup with left hand"
    finally:
        bot.stop()


def test_verify_clause_and_check_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ATLAS_LABEL_MODE", "verifier")
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        bot.open_work_queue()
        clauses = bot.discover_verifier_clauses()
        for clause in clauses:
            bot.verify_clause(clause, approve=True)
        bot.answer_missing_action(False)
        bot.click_check_answer()
        assert bot.page.locator("#checked").is_visible()
    finally:
        bot.stop()
