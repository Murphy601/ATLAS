import os
import re

# System prompt enforcing strict action-annotation formatting rules
SYSTEM_PROMPT = """
You are an expert AI video annotator strictly adhering to Standard Action Annotation Rules.

CRITICAL ANNOTATION RULES:
1. HAND-OBJECT CONTACT ONLY: Only label actions where human hands are actively interacting with an object.
   - If hands are idle, resting, walking, or moving without touching an object, output "No Action".
2. IMPERATIVE VOICE ONLY: Write labels as direct action commands (e.g., "pick up fork", "place plate on table").
   - NEVER use progressive or continuous verbs (e.g., "picking", "holding", "placing").
   - NEVER mention subject nouns like "person", "man", "woman", "hand", "she", or "he".
3. FORBIDDEN WORDS: Do NOT use terms like "inspect", "check", "reach", "examine", or "touch". Use "adjust", "grab", "hold", or "move" instead.
4. NO NUMERICAL DIGITS: Always write numbers as words (e.g., "two spoons", NOT "2 spoons").
5. PUNCTUATION & FORMATTING:
   - Separate distinct sequential actions using a comma "," or the word "and".
   - DO NOT end any label with a period ".".
   - Keep descriptions short, precise, and object-focused.

OUTPUT FORMAT:
Return ONLY the raw label string or "No Action". Do not include explanations, quotes, or conversational preamble.
"""

# Banned terminology for automated sanitization
FORBIDDEN_WORDS = [
    "inspect",
    "check",
    "reach",
    "examine",
    "touch",
    "touching",
    "holding",
    "picking",
    "placing",
]

# Verb mapping to convert progressive verbs into imperative commands
VERB_CORRECTIONS = {
    "picking up": "pick up",
    "holding": "hold",
    "placing": "place",
    "putting": "put",
    "taking": "take",
    "opening": "open",
    "closing": "close",
    "cutting": "cut",
    "grabbing": "grab",
    "moving": "move",
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
