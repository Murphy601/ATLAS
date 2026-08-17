import os
import re

from dotenv import load_dotenv

load_dotenv()

# System prompt enforcing Atlas Capture Standard Text Annotation Rules
SYSTEM_PROMPT = """
You are an expert video annotation bot for first-person (ego) video task labelling. Your sole job is to process input video keyframes or descriptions and output EXACT, audit-proof task labels according to strict guidelines.

A segment is ONE continuous interaction with a primary object toward a single goal.

#1 remaining fail: EXTRA ACTION. Do not invent pick up, hold, or micro-shifts.
#2 remaining fail: MISSING a real place/pass at the end, or a true off-hand stabilize.

Instrumental pickup: if the hand grabs a tool only to use it immediately, omit pick up.
  RIGHT: water plant with hose in right hand
  WRONG: pick up hose with right hand, water plant with hose in right hand
  RIGHT: iron shirt
  WRONG: pick up iron, iron shirt
Keep pick up ONLY when the object leaves a surface and is not immediately used, or when the next clause is place/set/pass.

Micro-movements inside cutting, wiping, digging, writing, watering, scrubbing are NOT extra clauses.

Max 3 clauses. Prefer one coarse verb when the motion is continuous.

Off-hand hold is required ONLY when that hand is clearly stabilizing a different role (hold paper, cut with scissors). Empty hand → do not mention it. Already in the hand at START → not pick up.

### 1. CORE SYNTAX & FORMATTING
* TEMPLATE: [action] [object] ([location]) with [hand]
* IMPERATIVE VOICE ONLY: Command form (e.g., "pick up spoon", "place cup on table"). NEVER use past/present tense ("picked", "picking").
* NO ARTICLES: NEVER write "a", "an", or "the".
* HAND MANDATE: Every action MUST specify the hand: "with left hand", "with right hand", "with both hands", or "with knife in right hand".
* SEPARATORS: Separate multiple actions using ONLY commas (,) or "and". NEVER use slashes (/), semicolons (;), or ", and".
* NO NUMERALS: Spell out numbers below ten ("three knives") or omit quantities ("knives"). NEVER write digits ("3").
* NO INTENT: Label only physical, observable actions. NEVER guess mental intent (e.g., write "pick up scissors", NOT "prepare to cut tape").
* NO TRAILING PERIOD.

### 2. BANNED VERBS & NOUNS (STRICT FAILURES)
* FORBIDDEN VERBS:
  - DO NOT USE "inspect" or "check" (looking/examining is NOT a hand action).
  - DO NOT USE "adjust" (use precise verbs: slide, shift, align, tilt, rotate, turn, flatten, straighten, tuck).
  - DO NOT USE "reach" (except when action is truncated at the exact end of an episode).
  - DO NOT USE "manipulate" (use grip, press, push, pull, twist, squeeze, pinch).
  - USE "grab" SPARINGLY (default to "pick up" unless the grip style is the focus).
* FORBIDDEN NOUNS: Do NOT use generic nouns like "tool", "object", or "utensil" if the specific item is identifiable (e.g., use "hoe", "trowel", "wrench", "knife", "scissors", "screwdriver"). "tool" FAILS audit.
* NEVER write generic "animal" by itself. A stuffed toy is "stuffed animal". A live pet is the species (dog, cat, sheep, goat, horse, cow, rabbit, pig, chicken) or a body part (fur, wool, ear, hoof).
* NO STORY WORDS: NEVER write then, next, after, before, first, or other. Labels are not narratives.
  WRONG: move soil from pot to other pot
  RIGHT: dig soil with hoe in right hand
* PLURAL-ONLY TOOLS (CRITICAL): Tools with two blades/jaws MUST ALWAYS BE PLURAL: "scissors", "tongs", "pliers" (NEVER "scissor").

### 3. WATCH THE FRAMES BEFORE YOU WRITE
EGO CAMERA: these images are from the worker's head. Do not mirror.
* The hand on the LEFT SIDE of the image is the LEFT hand.
* The hand on the RIGHT SIDE of the image is the RIGHT hand.
Compare FIRST frame (start) to LAST frame (end):
* pick up = object was at rest on a surface AND leaves it. If it is already in the hand in the FIRST frame, it is not pick up.
* hold = off-hand keeps gripping while the other hand does different work. Do not add hold for an empty hand or for the same tool already named.
* Micro shift/align/slide inside a continuous cut/wipe/dig/write/water/scrub is not its own clause.
* set = released onto ground.
* place = released onto a table, board, shelf, floor, or INTO a container. place ALWAYS needs a location.
* If an object is lifted at the end of the window, that is pick up, NOT hold.
* If an object is lowered onto floor/table at the end, that is place/set, NOT pick up.
* If the object STARTS in one hand and ENDS in the other, write a pass:
  pass bottle from right hand to left hand
* both hands = both hands are on the SAME tool doing the SAME motion (hose, dough). Not a substitute for hold + work.

### 4. ACTION COUNT: BOTH HANDS (CRITICAL)
Look at left hand, then right hand, in every frame.

CASE A — off-hand stabilize + working hand (two clauses, only if you SEE the stabilize):
  RIGHT: hold paper with left hand, cut paper with scissors in right hand
  WRONG: cut paper with scissors in right hand, hold scissors with left hand
  WRONG: pick up scissors with right hand, cut paper with scissors in right hand

CASE B — one continuous goal (ONE clause; this avoids Extra Action):
  RIGHT: water plant in bucket with hose in both hands
  RIGHT: dig soil with hoe in right hand
  RIGHT: work dough with both hands
  WRONG: pick up hoe with right hand, dig soil with hoe in right hand
  WRONG: dig soil with hoe in right hand, hold hoe with left hand

CASE C — real transfers (do not drop place/pass; do not add pickup-to-use):
  RIGHT: place hoe on ground with right hand, gather soil with both hands
  RIGHT: pick up wrench and place wrench on table with right hand
  RIGHT: pick up bottle with right hand, pass bottle from right hand to left hand
  WRONG: gather soil with both hands
  WRONG: pick up and place wrench with right hand

### 5. WHAT TO LABEL VS. IGNORE
* LABEL goal-directed hand–object actions that move the task forward.
* EVERY real pick up, set/place, pass, and task-relevant hold. Missed actions fail audit.
* NEVER LABEL: walking/navigating, looking, idle gestures, scratching, phone, camera.
* Hands touch nothing and do no task work → "No Action".
* Do not combine "No Action" with a real action.
* Do not split a segment just to isolate a short idle pause.

### 6. GRANULARITY: DENSE VS. COARSE
* A segment is 100% Dense OR 100% Coarse. NEVER mix in one label.
* COARSE (often safer): one goal verb covers continuous or repeated motion.
  work dough with both hands / scrub pan with brush / water plant in bucket with hose in both hands
  Repeated cycles inside ~10 seconds stay ONE coarse clause. Never write a repetition count.
* DENSE: list distinct actions only when no single goal verb is honest. Up to 3 clauses.
* Instrumental Pickup Rule: if pickup is only to do the goal immediately, do not write "pick up iron, iron shirt" — write "iron shirt". Same for hose/hoe/knife/brush used at once.
* Never exceed 3 atomic actions in one label. If more, drop micro-shifts and instrumental pickups first.
* "MOVE" RULE: "move [object] to [location]" is allowed as coarse relocation ONLY for segments 10 seconds or less. Otherwise: "pick up [object] with [hand], place [object] on [location] with [hand]".

### 7. OBJECT & LOCATION RULES
* fill [container] with [substance] with [tool] in [hand] when you can see the substance (water, soil).
* place needs a location. set is the verb for ground/floor.
* Adjectives ONLY to tell twins apart. Consistency: same object name and hand-state across segments.
* Avoid body parts unless unavoidable. Prefer "with right hand" over "with fingers".
* Attach every verb to an object: not "pick up, place on table" — "pick up cup, place cup on table".

### GOLD EXAMPLES
* GOLD EXAMPLES are FORMAT ONLY. Never output one of them unless those exact objects are in the frames.
* pick up nail polish bottle with left hand
* place nail polish bottle in box with left hand
* hold paper with left hand, cut paper with scissors in right hand
* hold mushrooms on board with left hand, chop mushrooms on board with knife in right hand
* place knife on board with right hand
* shift plastic bag with left hand, pick up plastic bag with right hand
* pass plastic bag to left hand, open plastic bag with both hands
* hold knife with right hand, place mushrooms in container with left hand, wipe knife with left hand
* water plant with hose in right hand
* water plant in bucket with hose in both hands
* fill watering can with water with hose in both hands
* set hose on ground with left hand, pick up watering can with right hand
* place bucket on floor with left hand, pick up hoe with right hand
* dig soil with hoe in right hand
* place hoe on ground with right hand, gather soil with both hands
* pick up bottle with right hand, pass bottle from right hand to left hand
* place bottle on counter with left hand
* hold wrench with left hand, pass wrench from left hand to right hand, place wrench on table with right hand
* pick up wrench and place wrench on table with right hand

### OUTPUT RULE
Output ONLY the raw label string or "No Action". No explanation, no intro text, no conversational filler, and no markdown wrapping.
"""

# Used when captured frames have video texture. The long prompt's "or No Action"
# override made every model dump No Action even on insist retries.
ACTION_SYSTEM_PROMPT = """
You label first-person occupational hand-work stills for Atlas Capture.
Output ONLY one Atlas label. Never write No Action. Never explain. Never refuse.

TEMPLATE: verb + object + with [left hand|right hand|both hands]
No articles (a/an/the). No digits. No trailing period.
No inspect, check, adjust, reach, manipulate, then, next, other, or generic tool/animal.
Max 3 comma-separated clauses. LEFT side of each image is the LEFT hand.

both hands ONLY when both hands do the SAME motion on the SAME object (knead dough, lift a box).
If the hands have different jobs, write TWO clauses. Never hide that as both hands.
  RIGHT: hold glass plate with left hand, wipe glass plate with cloth in right hand
  WRONG: wipe plate with both hands
  WRONG: hold bowl with both hands
A clear dish is glass plate, not bowl. Name the wiping cloth if you see it.

#1 EXTRA ACTION: do not invent pick up or micro-shifts.
If they grab a tool only to use it immediately, omit pick up.
  RIGHT: water plant with hose in right hand
  WRONG: pick up hose with right hand, water plant with hose in right hand
Do not write shift/align/slide/tilt/tap inside cut/wipe/dig/water/write/scrub.
Do not write hold of the SAME tool already named in the work clause.
Max 3 clauses. Prefer one coarse verb for continuous motion.

#2 MISSING ACTION: do write place/set/pass if the object is released or changes hands.
If one hand keeps the workpiece still while the other works with a different tool, write BOTH clauses.
  RIGHT: hold glass plate with left hand, wipe glass plate with cloth in right hand
  RIGHT: hold paper with left hand, cut paper with scissors in right hand
  WRONG: wipe glass plate with cloth in right hand
Empty hand → do not mention it. Already in the hand at START → not pick up.

Every clause needs a verb, an object, and a hand. No articles. No then/next/other.

If the object is already in the hand in the first frame, do not write pick up.
Name the object you see. Do not copy gold-style examples unless they are visible.
"""

# Banned terminology for automated sanitization
FORBIDDEN_WORDS = [
    "inspect",
    "check",
    "examine",
    "adjust",
    "reach",
    "manipulate",
    "touching",
    "holding",
    "picking",
    "placing",
]

# Looking / idle verbs: not hand actions. Drop them; do not replace with "adjust".
LOOKING_VERBS = [
    "inspect",
    "check",
    "examine",
    "look at",
    "looking at",
    "looking",
]

# Verb mapping to convert progressive verbs into imperative commands
VERB_CORRECTIONS = {
    "picking up": "pick up",
    "picked up": "pick up",
    "holding": "hold",
    "placing": "place",
    "putting": "put",
    "taking": "take",
    "opening": "open",
    "closing": "close",
    "cutting": "cut",
    "grabbing": "grab",
    "moving": "move",
    "adjusting": "shift",
    "reaching": "move",
    "manipulating": "grip",
    "chopping": "chop",
    "sliding": "slide",
    "shifting": "shift",
    "aligning": "align",
    "rotating": "rotate",
    "squeezing": "squeeze",
    "folding": "fold",
    "passing": "pass",
    "filling": "fill",
    "setting": "set",
    "stabilizing": "hold",
}

# Banned verb replacements that stay audit-safe
VERB_REPLACEMENTS = {
    "adjust": "shift",
    "manipulate": "grip",
    "touching": "hold",
    "touch": "hold",
    "grab": "pick up",
    "stabilize": "hold",
}

# Mapping digits to words for string replacement
NUMBER_MAP = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "10": "ten",
}

# Regex pattern matching standalone digits
DIGIT_PATTERN = re.compile(r"\b\d+\b")
ARTICLE_PATTERN = re.compile(r"\b(?:the|a|an)\b", re.IGNORECASE)
COMMA_AND_PATTERN = re.compile(r",\s*and\b", re.IGNORECASE)
SLASH_PATTERN = re.compile(r"\s*/\s*")
SEMICOLON_PATTERN = re.compile(r"\s*;\s*")
HAND_PATTERN = re.compile(
    r"\b(?:left hand|right hand|both hands|\w+ in (?:left|right) hand)\b",
    re.IGNORECASE,
)

# Tools that must always be plural
PLURAL_ONLY_TOOLS = {
    "scissor": "scissors",
    "plier": "pliers",
    "tong": "tongs",
}

# Relocation / transfer verbs. A trailing "hold" after these is a second real action.
TRANSFER_VERBS = {
    "pick up",
    "place",
    "set",
    "pass",
    "put",
    "put down",
    "drop",
    "move",
    "hold",
    "grab",
    "carry",
    "hand",
}

# Visible fill medium when the source is a hose/tap
FILL_SOURCE_TOOLS = ("hose", "tap", "faucet", "spout")

# Story words the Atlas grader rejects (Rule 3)
NARRATIVE_WORDS = (
    "then",
    "next",
    "after",
    "before",
    "first",
    "afterwards",
    "finally",
    "other",
)

# Prefer these names when a label says "tool" / "object" / "utensil"
NAMED_IMPLEMENTS = (
    "watering can",
    "nail polish bottle",
    "plastic bag",
    "snack bag",
    "metal pin",
    "syrup bottle",
    "refrigerator door",
    "bicycle wheel",
    "cutting board",
    "hoe",
    "trowel",
    "shovel",
    "rake",
    "wrench",
    "hammer",
    "screwdriver",
    "pliers",
    "scissors",
    "tongs",
    "bottle",
    "sachet",
    "bucket",
    "hose",
    "knife",
    "spoon",
    "fork",
    "cup",
    "bowl",
    "plate",
    "cloth",
    "pan",
    "bag",
    "pin",
)

GENERIC_NOUNS = ("tool", "object", "utensil", "item")

# Coarse FORMAT examples models copy when they cannot see the video (see Segment 3 log).
PROMPT_EXAMPLE_LABELS = frozenset(
    {
        "work dough with both hands",
        "scrub pan with brush",
        "iron shirt",
    }
)

MAX_ACTIONS_PER_LABEL = 3

# Goal-use verbs: pick up of the same tool right before these is instrumental (extra action).
USE_VERBS = {
    "water",
    "fill",
    "cut",
    "chop",
    "dig",
    "wipe",
    "iron",
    "scrub",
    "wash",
    "stir",
    "mix",
    "spray",
    "sweep",
    "shovel",
    "work",
    "knead",
    "fold",
    "flatten",
    "tighten",
    "squeeze",
    "scrape",
    "scoop",
    "pour",
    "rinse",
    "smooth",
    "gather",
    "pack",
    "peel",
    "write",
    "brush",
    "sand",
    "hammer",
    "drill",
    "trim",
    "unfold",
    "open",
    "close",
}

MICRO_VERBS = {"shift", "align", "slide", "tilt", "tap", "pat"}
WORK_MICROS = MICRO_VERBS
KEEP_PICKUP_BEFORE = {
    "place",
    "set",
    "pass",
    "put",
    "put down",
    "drop",
    "move",
}
MISSING_IF_DROPPED = {"place", "set", "pass", "gather"}
CONTINUOUS_VERBS = {
    "cut",
    "chop",
    "wipe",
    "write",
    "dig",
    "water",
    "scrub",
    "iron",
    "work",
    "knead",
    "stir",
    "wash",
    "smooth",
    "gather",
    "sweep",
    "trim",
    "unfold",
}

# AI API Configuration — OpenRouter (paid vision models, cheapest first)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/Murphy601/ATLAS",
    "X-Title": "ATLAS Video Labeling Bot",
}
LABEL_PROVIDER = os.getenv("LABEL_PROVIDER", "openrouter")
TEMPERATURE = 0.1  # Ensures low variability and deterministic outputs

# Claude 3.7 Sonnet and Gemini 1.5 Pro 404 on OpenRouter.
# gpt-4o refuses egocentric hand images ("I'm sorry, I can't assist with that").
DEFAULT_MODELS = [
    "google/gemini-2.5-flash",
    "qwen/qwen2.5-vl-72b-instruct",
    "google/gemini-2.5-pro",
]
_primary_model = (os.getenv("VISION_MODEL") or "").strip()
VISION_MODELS = (
    [_primary_model] + [m for m in DEFAULT_MODELS if m != _primary_model]
    if _primary_model
    else list(DEFAULT_MODELS)
)
# OpenRouter rejects route fallback lists longer than 3.
OPENROUTER_MAX_ROUTE_FALLBACKS = 3

# Atlas Capture audit portal selectors
SELECTORS = {
    "label_input": 'input[aria-label*="label"]',
    "label_input_alt": 'input[data-ph-unmask="true"]',
    "segment_input": 'input[data-segment-start-seconds], input[aria-label^="Segment"][aria-label*="label"]',
    "video": "video",
    "play_button": 'button[aria-label*="Play" i], button:has-text("Play")',
    "play_segment": 'button:has-text("Play segment")',
    "tasks_nav": 'a:has-text("Tasks"), button:has-text("Tasks"), [href*="/tasks"]',
    "continue_practice": 'button:has-text("Continue Assessment Practice"), a:has-text("Continue Assessment Practice")',
    "review_task": 'button:has-text("Review"), a:has-text("Review")',
    "start_task": 'button:has-text("Start"), a:has-text("Start"), button:has-text("Open")',
    "next_task": 'button:has-text("Next task"), button:has-text("Next clip"), button:has-text("Next episode"), button:has-text("Next video"), a:has-text("Next task")',
    "next_generic": 'button:has-text("Next"), a:has-text("Next")',
    "submit_button": 'button:has-text("Submit practice clip"), button:has-text("Submit clip"), button:has-text("Submit episode"), button:has-text("Submit video")',
    "submit_button_generic": 'button[data-slot="button"]:has-text("Submit"), button:has-text("Complete"), button:has-text("Submit assessment")',
    "submit_btn": 'button:has-text("Submit practice clip"), button[data-slot="button"]:has-text("Submit"), button:has-text("Submit"), button:has-text("Complete"), button[type="submit"]',
}

# Pipeline defaults (overridable via environment variables)
DEFAULT_PORTAL_URL = os.getenv("PORTAL_URL", "https://audit.atlascapture.io/")
DEFAULT_SEGMENT_DURATION = float(os.getenv("SEGMENT_DURATION", "3.0"))
DEFAULT_FRAME_INTERVAL = float(os.getenv("FRAME_INTERVAL", "0.5"))
MIN_FRAMES_PER_SEGMENT = int(os.getenv("MIN_FRAMES_PER_SEGMENT", "5"))
MAX_FRAMES_PER_SEGMENT = int(os.getenv("MAX_FRAMES_PER_SEGMENT", "10"))
