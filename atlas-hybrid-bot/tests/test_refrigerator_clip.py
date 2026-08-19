from label_pipeline import atlas_guide_cleaner, normalize_episode_sequence


def test_dual_container_pickup_kept_separate_hands():
    """Two small containers: one per hand, not both hands on one object."""
    draft = (
        "pick up container with left hand, pick up container with right hand, "
        "walk to refrigerator"
    )
    out = atlas_guide_cleaner(draft)
    assert out.lower() == (
        "pick up container with left hand, pick up container with right hand"
    )


def test_refrigerator_episode_hold_reposition_then_place():
    labels = [
        "pick up container with left hand, pick up container with right hand",
        "reposition items in refrigerator with right hand, place container in refrigerator with right hand",
        "reposition items in refrigerator with right hand, place container in refrigerator with right hand",
        "reposition items in refrigerator with right hand, place container in refrigerator with right hand",
    ]
    out = normalize_episode_sequence(labels)
    assert out[0].lower() == (
        "pick up container with left hand, pick up container with right hand"
    )
    assert out[1].lower() == (
        "hold container with left hand, reposition items in refrigerator with right hand"
    )
    assert out[2].lower() == out[1].lower()
    assert out[3].lower() == "place container in refrigerator with right hand"
