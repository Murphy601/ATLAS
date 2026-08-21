from pathlib import Path

import config
from browser_automation import VideoBrowserBot
from verifier_logic import decide_clause_verification, decide_missing_action

FIXTURE = Path(__file__).parent / "fixtures" / "verifier_portal.html"


def test_decide_clause_verification_accepts_valid_grammar():
    clauses = [
        "hold glass cup with left hand",
        "scrub glass cup with sponge in right hand",
    ]
    assert decide_clause_verification(clauses[0], clauses, index=0)
    assert decide_clause_verification(clauses[1], clauses, index=1)


def test_decide_clause_verification_rejects_duplicate():
    clauses = [
        "scoop food from container into pot with spoon in right hand",
        "scoop food from container into pot with spoon in right hand",
    ]
    assert decide_clause_verification(clauses[0], clauses, index=0)
    assert not decide_clause_verification(clauses[1], clauses, index=1)


def test_decide_missing_action_when_expected_has_extra_clause():
    shown = ["hold bottle with right hand"]
    expected = "hold bottle with right hand, pass bottle from right hand to left hand"
    assert decide_missing_action(shown, expected_label=expected)


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
