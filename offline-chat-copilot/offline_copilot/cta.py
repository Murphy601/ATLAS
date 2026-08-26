"""Open-ended CTA bank. Each item is one question. No meetup, dating, or contact asks."""

from __future__ import annotations

import itertools


def _unique(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = " ".join(item.split())
        if not text.endswith("?"):
            continue
        if text.count("?") != 1:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return tuple(out)


def build_cta_bank() -> tuple[str, ...]:
    questions: list[str] = [
        "What's been the highlight of your week so far?",
        "How do you usually like to unwind after a long day?",
        "If you could jump on a plane just for the scenery, where would you go?",
        "What kind of music have you had on repeat lately?",
        "Are you more of a stay-in person on weekends, or do you like getting out?",
        "What's your favorite way to spend a Sunday afternoon?",
        "Are you big into watching sports, or do other hobbies win most nights?",
        "Did you catch any of the games over the weekend?",
        "What's your favorite team to root for?",
        "What show or movie has actually held your attention lately?",
        "Coffee, tea, or something cold when you need a reset?",
        "What's one small thing that made today better?",
        "How do you usually kick off a weekday morning?",
        "What's the last meal you cooked that you were actually proud of?",
        "Are you more of a morning person or a night owl?",
        "What's a hobby you'd pick back up if time magically appeared?",
        "What kind of weather puts you in the best mood?",
        "What's your go-to playlist when you're driving?",
        "If you had a completely free Saturday, how would you spend it?",
        "What's something you've gotten surprisingly good at over the years?",
    ]
    times = [
        "a long day",
        "a quiet evening",
        "a free Sunday",
        "a random weekday",
        "the weekend",
        "a slow morning",
        "work",
        "a busy week",
        "errands",
        "a late night",
    ]
    verbs = [
        "unwind",
        "recharge",
        "reset",
        "stay entertained",
        "keep things interesting",
        "treat yourself",
        "slow the pace",
    ]
    for time, verb in itertools.product(times, verbs):
        questions.append(f"How do you usually {verb} after {time}?")

    hobbies = [
        "grilling",
        "photography",
        "classic cars",
        "fishing",
        "live music",
        "home projects",
        "gardening",
        "baking",
        "gaming",
        "hiking trails near home",
        "basketball",
        "baseball",
        "football",
        "sci-fi movies",
        "podcasts",
        "coffee setups",
        "vintage records",
        "weightlifting",
        "cooking new recipes",
        "weekend drives",
        "woodworking",
        "cycling",
        "swimming",
        "camping gear",
        "board games",
        "stand-up comedy specials",
        "true-crime documentaries",
        "soccer",
        "hockey",
        "trivia",
        "hot sauce collecting",
        "smoking meat",
        "restoring furniture",
        "houseplants",
        "guitar",
        "karaoke playlists",
        "food trucks",
        "thrift shopping",
        "pc building",
        "fantasy football",
    ]
    hobby_asks = [
        "What got you into {hobby} in the first place?",
        "What's your favorite part of {hobby} these days?",
        "How did {hobby} become a thing you actually look forward to?",
        "If you had a spare afternoon, how would {hobby} fit in?",
        "What would make {hobby} even more fun for you?",
        "Is {hobby} more of a solo thing or something you like talking about?",
    ]
    for hobby, ask in itertools.product(hobbies, hobby_asks):
        questions.append(ask.format(hobby=hobby))

    rather_a = [
        "stay in with a good show",
        "take a long drive",
        "cook something from scratch",
        "catch a game on TV",
        "put music on and zone out",
        "start a house project",
        "sleep in",
        "go for a walk",
    ]
    rather_b = [
        "get outside for a bit",
        "work on a project around the house",
        "call it an early night",
        "try a new recipe",
        "browse something new to watch",
        "put a game on in the background",
        "clean the garage and put music on",
        "make a big breakfast",
    ]
    for a, b in itertools.product(rather_a, rather_b):
        if a == b:
            continue
        questions.append(f"Would you rather {a} or {b}?")

    sports = [
        "UFC fight nights",
        "MLB regular-season games",
        "NFL pre-season",
        "college football",
        "playoff baseball",
        "late-night highlights",
    ]
    for item in sports:
        questions.append(f"Are you more into {item}, or do you just catch bits and pieces?")
        questions.append(f"What do you like most about {item}?")

    details = [
        "a great burger",
        "a perfect cup of coffee",
        "a road-trip playlist",
        "a lazy Sunday breakfast",
        "a well-made sandwich",
        "a backyard cookout",
        "a rainy-day movie",
        "a late-night snack",
        "a first-pitch baseball game",
        "a clean house after a project day",
    ]
    for detail in details:
        questions.append(f"What makes {detail} actually worth it for you?")
        questions.append(f"When was the last time {detail} really hit the spot?")

    openers = [
        "What's one thing",
        "What's something small",
        "What's a recent thing",
    ]
    tails = [
        "that always puts you in a better mood?",
        "you'd tell a friend about from this week?",
        "you wish you had more time for?",
        "you never get tired of talking about?",
        "that still makes you laugh when you think about it?",
    ]
    for opener, tail in itertools.product(openers, tails):
        questions.append(f"{opener} {tail}")

    seasons = ["spring", "summer", "fall", "winter"]
    season_asks = [
        "What's the best part of {season} for you?",
        "What do you always want to do more of in {season}?",
        "How do you usually spend a {season} weekend at home?",
        "What food just tastes better to you in {season}?",
        "What {season} habit do you actually keep?",
    ]
    for season, ask in itertools.product(seasons, season_asks):
        questions.append(ask.format(season=season))

    numbers = [
        "one",
        "two",
        "a couple of",
    ]
    extras = [
        "albums you'd save",
        "meals you could eat every week",
        "games you'd rewatch",
        "places you'd visit just for the view",
        "skills you'd teach a friend",
        "shows you'd recommend",
        "cars you'd take on a long drive",
        "recipes you'd make for a crowd",
    ]
    for number, extra in itertools.product(numbers, extras):
        questions.append(f"If you had to pick {number} {extra}, what would they be?")

    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    weekday_asks = [
        "What does a good {day} look like for you?",
        "How do you usually feel heading into {day}?",
        "What's your {day} evening routine when you actually have energy?",
    ]
    for day, ask in itertools.product(weekdays, weekday_asks):
        questions.append(ask.format(day=day))

    return _unique(questions)


CTA_BANK = build_cta_bank()
INTIMATE_CTAS = _unique(
    [
        "Want me to go that slow with my mouth, or a little greedier?",
        "Should I stay on top of you while I kiss my way down?",
        "Does that kind of attention sound like what you were craving?",
        "Want me to tell you how I'd sound when you find it?",
        "Should I keep teasing you like that, or take more of you in?",
        "Do you want me kissing you the whole time I work my way down?",
        "Should I take my time on you, or let you feel how hungry I am?",
        "Want me to stay right there until you tell me you can't wait?",
    ]
)
VALIDATION_CTAS = _unique(
    [
        "What made you feel like you could tell me that?",
        "Does it help if I tell you I feel that same pull with you?",
        "Want me to keep talking to you like this?",
        "How long have you been holding that in?",
    ]
)
CTA_BY_CATEGORY = {
    "general": tuple(q for q in CTA_BANK if not any(w in q.casefold() for w in ("ufc", "mlb", "nfl", "game", "baseball", "football", "fight"))),
    "sports": tuple(q for q in CTA_BANK if any(w in q.casefold() for w in ("ufc", "mlb", "nfl", "game", "baseball", "football", "fight", "team", "sports"))),
    "weekend": tuple(q for q in CTA_BANK if any(w in q.casefold() for w in ("weekend", "sunday", "saturday"))),
    "intimate": INTIMATE_CTAS,
    "validation": VALIDATION_CTAS,
}
