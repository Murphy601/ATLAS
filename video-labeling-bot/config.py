import os
import re

# System prompt enforcing Atlas Capture Standard Text Annotation Rules
SYSTEM_PROMPT = """
You are an expert video annotation bot for first-person (ego) video task labelling. Your sole job is to process input video keyframes or descriptions and output EXACT, audit-proof task labels according to strict guidelines.

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

### 3. WHAT TO LABEL VS. IGNORE
* LABEL:
  - All goal-directed hand actions (e.g., "unfold paper with left hand, pick up brush with right hand").
  - EVERY pick up, place, hold, dip, and hand-to-hand pass. (Missed actions are the #1 audit failure—account for BOTH hands throughout the entire segment!).
* NEVER LABEL (Return "No Action" or omit):
  - Ego walking/moving through space.
  - Looking, checking, idle gestures, scratching, phone use, or adjusting head-cameras.
  - Idle time where hands touch nothing and perform no task work (Use "No Action").
* Do not combine "No Action" with a real action in the same label.

### 4. GRANULARITY: DENSE VS. COARSE
* DENSE: Lists distinct atomic actions (up to 3 per segment). Required when multiple distinct actions occur with no single overarching verb.
* COARSE: Uses one goal verb covering continuous motions (e.g., "work dough with both hands", "scrub pan with brush").
  - Use coarse for repeated cycles (never count/enumerate repetitive motions like "chop 7 times").
  - Instrumental Pickup Rule: If an item is picked up solely to perform an immediate goal (e.g., "iron shirt"), DO NOT write "pick up iron, iron shirt"—use the single coarse action.
* "MOVE" RULE: "move [object] to [location]" is allowed as a coarse verb ONLY for relocations lasting 10 seconds or less. Otherwise, write explicit dense steps: "pick up [object] with [hand], place [object] on [location] with [hand]".
* SEGMENT RULE: A label MUST be 100% Dense OR 100% Coarse. NEVER mix dense and coarse syntax in a single label!

### 5. OBJECT & LOCATION RULES
* LOCATIONS REQUIRED FOR 'PLACE': "place" MUST include a target location (e.g., "place cup on table with left hand", "place cup in bin with right hand").
* ADJECTIVES: Include adjectives ONLY to distinguish between two similar items on screen (e.g., "blue cloth" vs "white cloth"). If there is only one, omit the color/adjective ("cloth").
* CONSISTENCY: Keep naming consistent across segments (don't switch from "component" to "metal part", or "wash" to "clean").
* Avoid body parts unless unavoidable. Prefer "with right hand" over "with fingers".

### GOLD EXAMPLES
* pick up nail polish bottle with left hand
* place nail polish bottle in box with left hand
* hold mushrooms on board with left hand, chop mushrooms on board with knife in right hand
* place knife on board with right hand
* shift plastic bag with left hand, pick up plastic bag with right hand
* pass plastic bag to left hand, open plastic bag with both hands
* hold knife with right hand, place mushrooms in container with left hand, wipe knife with left hand

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

# Atlas Capture audit portal selectors
SELECTORS = {
    "label_input": 'input[aria-label*="label"]',
    "label_input_alt": 'input[data-ph-unmask="true"]',
    "segment_input": 'input[data-segment-start-seconds], input[aria-label^="Segment"][aria-label*="label"]',
    "video": "video",
    "play_button": 'button[aria-label*="Play" i], button:has-text("Play")',
    "submit_button": 'button:has-text("Submit practice clip")',
    "submit_button_generic": 'button[data-slot="button"]:has-text("Submit")',
    "submit_btn": 'button:has-text("Submit practice clip"), button[data-slot="button"]:has-text("Submit"), button:has-text("Submit"), button:has-text("Next"), button[type="submit"]',
}

# Pipeline defaults (overridable via environment variables)
DEFAULT_PORTAL_URL = os.getenv("PORTAL_URL", "https://audit.atlascapture.io/")
DEFAULT_SEGMENT_DURATION = float(os.getenv("SEGMENT_DURATION", "3.0"))
DEFAULT_FRAME_INTERVAL = float(os.getenv("FRAME_INTERVAL", "1.0"))
