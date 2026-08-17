import os
import re

# System prompt enforcing Atlas Capture Standard Text Annotation Rules
SYSTEM_PROMPT = """
You are an expert video annotation bot for first-person (ego) video task labelling. Your sole job is to process input video keyframes or descriptions and output EXACT, audit-proof task labels according to strict guidelines.

A segment is ONE continuous interaction with a primary object toward a SINGLE GOAL. The practice grader COUNTS COMMA-SEPARATED CLAUSES as separate actions. If the window is 1 action and you write 2 clauses, you FAIL.

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
* FORBIDDEN NOUNS: Do NOT use generic nouns like "tool", "object", or "utensil" if the specific item is identifiable (e.g., use "knife", "scissors", "screwdriver").
* PLURAL-ONLY TOOLS (CRITICAL): Tools with two blades/jaws MUST ALWAYS BE PLURAL: "scissors", "tongs", "pliers" (NEVER "scissor").

### 3. WATCH THE FRAMES BEFORE YOU WRITE
Compare the FIRST frame (segment start) to the LAST frame (segment end):
* pick up = object was at rest and LEAVES a surface or container.
* hold = object STAYS in the same hand and is not relocated. Use hold only when that off-hand stabilize is a DISTINCT action on a DIFFERENT object.
* set = object is released onto ground or floor.
* place = object is released onto a table, board, shelf, or INTO a container. place ALWAYS needs a location.
* If an object is lifted at the end of the window, that is pick up, NOT hold.
* If both hands are on the SAME tool for the SAME goal, that is ONE action with both hands. Do not invent a second hold clause.

### 4. ACTION COUNT: BOTH HANDS VS HOLD (CRITICAL)
The grader error "The window contains 1 action(s); the label states 2." means you over-split.

CASE A — same goal, hands cooperating on one tool/object:
Write ONE coarse clause with "both hands" or "with [tool] in both hands".
  RIGHT: water plant in bucket with hose in both hands
  WRONG: water plant in bucket with hose in left hand, hold watering can with right hand
  RIGHT: fill watering can with water with hose in both hands
  WRONG: fill watering can with hose in left hand, hold watering can with right hand
Never add "hold X with [other] hand" just to mention the unused hand. Use both hands instead.

CASE B — two distinct roles or two distinct objects:
Then list them (max 3). Off-hand stabilize + working hand IS two actions:
  RIGHT: hold mushrooms on board with left hand, chop mushrooms on board with knife in right hand
  RIGHT: set hose on ground with left hand, pick up watering can with right hand
  WRONG: place hose on ground with left hand, hold watering can with right hand
        (left SETS the hose down; right PICKS UP the can — that is not a hold)

CASE C — account for a missed action only when it is real:
Pass, dip, and a true pick up/place/set must appear. Do not drop a real second action. Do not invent a hold.

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
* Instrumental Pickup Rule: if pickup is only to do the goal immediately, do not write "pick up iron, iron shirt" — write "iron shirt".
* "MOVE" RULE: "move [object] to [location]" is allowed as coarse relocation ONLY for segments 10 seconds or less. Otherwise: "pick up [object] with [hand], place [object] on [location] with [hand]".

### 7. OBJECT & LOCATION RULES
* fill [container] with [substance] with [tool] in [hand] when you can see the substance (water, soil).
* place needs a location. set is the verb for ground/floor.
* Adjectives ONLY to tell twins apart. Consistency: same object name and hand-state across segments.
* Avoid body parts unless unavoidable. Prefer "with right hand" over "with fingers".
* Attach every verb to an object: not "pick up, place on table" — "pick up cup, place cup on table".

### GOLD EXAMPLES
* pick up nail polish bottle with left hand
* place nail polish bottle in box with left hand
* hold mushrooms on board with left hand, chop mushrooms on board with knife in right hand
* place knife on board with right hand
* shift plastic bag with left hand, pick up plastic bag with right hand
* pass plastic bag to left hand, open plastic bag with both hands
* hold knife with right hand, place mushrooms in container with left hand, wipe knife with left hand
* water plant in bucket with hose in both hands
* fill watering can with water with hose in both hands
* set hose on ground with left hand, pick up watering can with right hand

### OUTPUT RULE
Output ONLY the raw label string or "No Action". No explanation, no intro text, no conversational filler, and no markdown wrapping.
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
}

# Banned verb replacements that stay audit-safe
VERB_REPLACEMENTS = {
    "adjust": "shift",
    "manipulate": "grip",
    "touching": "hold",
    "touch": "hold",
    "grab": "pick up",
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

# AI API Configuration — OpenRouter free vision models
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/Murphy601/ATLAS",
    "X-Title": "ATLAS Video Labeling Bot",
}
LABEL_PROVIDER = os.getenv("LABEL_PROVIDER", "openrouter")
TEMPERATURE = 0.1  # Ensures low variability and deterministic outputs

# Primary free VLMs, then fallbacks, then OpenRouter auto-router
VISION_MODELS = [
    "qwen/qwen-2-vl-7b-instruct:free",
    "google/gemini-2.5-flash:free",
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
    "mistralai/pixtral-12b:free",
    "qwen/qwen-2.5-vl-72b-instruct:free",
    "openrouter/auto",
]
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
    "next_task": 'button:has-text("Next task"), button:has-text("Next clip"), button:has-text("Next episode"), a:has-text("Next task")',
    "next_generic": 'button:has-text("Next"), a:has-text("Next")',
    "submit_button": 'button:has-text("Submit practice clip")',
    "submit_button_generic": 'button[data-slot="button"]:has-text("Submit")',
    "submit_btn": 'button:has-text("Submit practice clip"), button[data-slot="button"]:has-text("Submit"), button:has-text("Submit"), button[type="submit"]',
}

# Pipeline defaults (overridable via environment variables)
DEFAULT_PORTAL_URL = os.getenv("PORTAL_URL", "https://audit.atlascapture.io/")
DEFAULT_SEGMENT_DURATION = float(os.getenv("SEGMENT_DURATION", "3.0"))
DEFAULT_FRAME_INTERVAL = float(os.getenv("FRAME_INTERVAL", "1.0"))
