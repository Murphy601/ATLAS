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

# AI API Configuration
OPENAI_MODEL = "gpt-4o"
# Architecture alternative (not used unless LABEL_PROVIDER=qwen): Qwen2-VL
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen2-vl")
LABEL_PROVIDER = os.getenv("LABEL_PROVIDER", "openai")
TEMPERATURE = 0.1  # Ensures low variability and deterministic outputs

# Pipeline defaults (overridable via environment variables)
DEFAULT_PORTAL_URL = os.getenv("PORTAL_URL", "https://audit.atlascapture.io/")
DEFAULT_SEGMENT_DURATION = float(os.getenv("SEGMENT_DURATION", "3.0"))
DEFAULT_FRAME_INTERVAL = float(os.getenv("FRAME_INTERVAL", "1.0"))
