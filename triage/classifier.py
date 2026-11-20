"""Suggest a category + one-line summary for a ticket.

Three interchangeable classifiers:
  - KeywordClassifier: no AI, works offline, always available as the fallback.
  - OllamaClassifier:  a local model, so ticket data never leaves the machine.
  - OpenAIClassifier:  any OpenAI-compatible endpoint.

LLM output is never trusted as-is: it must be valid JSON with an allowed category,
otherwise we fall back to keywords and flag the ticket for a human.
"""

import json
import logging
import re
from dataclasses import dataclass

import requests

from .config import CATEGORIES
from .jira_client import Issue

log = logging.getLogger(__name__)


@dataclass
class Suggestion:
    category: str
    summary: str
    confidence: float
    source: str  # which classifier produced it
    needs_human: bool  # True when confidence is low or the LLM output was rejected


# --- Privacy: strip personal data before any text goes to a model ---------------------------

REDACTIONS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\b\d{14}\b"), "[NATIONAL_ID]"),  # Egyptian national ID is 14 digits
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD_OR_ACCOUNT]"),
    (re.compile(r"(?:\+?20|0)1[0125]\d{8}\b"), "[PHONE]"),  # Egyptian mobile numbers
]


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


# --- Baseline: keyword rules -----------------------------------------------------------------

KEYWORDS = {
    "access_request": ["access", "permission", "login", "password", "locked", "role", "grant"],
    "performance": ["slow", "timeout", "latency", "hangs", "takes forever", "loading"],
    "data_fix": ["wrong data", "duplicate", "incorrect", "correct the", "update record", "mismatch"],
    "bug": ["error", "fails", "failed", "broken", "crash", "exception", "500", "not working"],
    "how_to": ["how do i", "how to", "where can i", "is it possible", "guide"],
    "feature_request": ["feature", "would be nice", "add a", "request to add", "enhancement"],
}


class KeywordClassifier:
    name = "keyword"

    def classify(self, issue: Issue) -> Suggestion:
        text = f"{issue.summary} {issue.description}".lower()
        scores = {cat: sum(word in text for word in words) for cat, words in KEYWORDS.items()}
        best = max(scores, key=scores.get)
        hits = scores[best]
        if hits == 0:
            return Suggestion("other", issue.summary[:120], 0.2, self.name, needs_human=True)
        confidence = min(0.4 + 0.15 * hits, 0.8)  # keyword rules never claim high certainty
        return Suggestion(best, issue.summary[:120], confidence, self.name, needs_human=confidence < 0.6)


# --- LLM classifiers ------------------------------------------------------------------------

PROMPT = """You triage internal IT support tickets at a bank.
Return ONLY a JSON object with these keys:
  "category": one of {categories}
  "summary": one sentence, max 20 words
  "confidence": a number from 0.0 to 1.0

Ticket title: {title}
Ticket description:
{description}"""


def validate(raw_text: str, source: str) -> Suggestion:
    """Parse and check model output. Raises ValueError if it can't be trusted."""
    data = json.loads(raw_text)
    category = data.get("category")
    if category not in CATEGORIES:
        raise ValueError(f"category {category!r} not allowed")
    summary = str(data.get("summary", "")).strip()
    if not summary:
        raise ValueError("empty summary")
    confidence = float(data.get("confidence", 0))
    if not 0 <= confidence <= 1:
        raise ValueError(f"confidence {confidence} out of range")
    return Suggestion(category, summary[:200], confidence, source, needs_human=confidence < 0.7)


class _LLMClassifier:
    name = "llm"

    def __init__(self, base_url: str, model: str, session: requests.Session, api_key: str = ""):
        self.base_url = base_url
        self.model = model
        self.session = session
        self.api_key = api_key
        self.fallback = KeywordClassifier()

    def prompt_for(self, issue: Issue) -> str:
        return PROMPT.format(
            categories=CATEGORIES,
            title=redact(issue.summary),
            description=redact(issue.description)[:3000],  # stay well inside the context window
        )

    def call_model(self, prompt: str) -> str:
        raise NotImplementedError

    def classify(self, issue: Issue) -> Suggestion:
        try:
            return validate(self.call_model(self.prompt_for(issue)), self.name)
        except (requests.RequestException, ValueError, KeyError) as exc:
            # ValueError also covers bad JSON (json.JSONDecodeError subclasses it).
            log.warning("%s: model output rejected (%s); using keyword fallback", issue.key, exc)
            suggestion = self.fallback.classify(issue)
            suggestion.needs_human = True
            return suggestion


class OllamaClassifier(_LLMClassifier):
    name = "ollama"

    def call_model(self, prompt: str) -> str:
        resp = self.session.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


class OpenAIClassifier(_LLMClassifier):
    name = "openai"

    def call_model(self, prompt: str) -> str:
        resp = self.session.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class DeepSeekClassifier(OpenAIClassifier):
    """DeepSeek's API is OpenAI-compatible, so only the defaults differ."""

    name = "deepseek"
    DEFAULT_BASE_URL = "https://api.deepseek.com"
    DEFAULT_MODEL = "deepseek-flash"


def build_classifier(kind: str, base_url: str, model: str, api_key: str, session: requests.Session):
    if kind == "ollama":
        return OllamaClassifier(base_url or "http://localhost:11434", model or "llama3.2", session)
    if kind == "openai":
        if not (base_url and model):
            raise ValueError("CLASSIFIER=openai needs LLM_BASE_URL and LLM_MODEL")
        return OpenAIClassifier(base_url, model, session, api_key)
    if kind == "deepseek":
        if not api_key:
            raise ValueError("CLASSIFIER=deepseek needs LLM_API_KEY")
        return DeepSeekClassifier(
            base_url or DeepSeekClassifier.DEFAULT_BASE_URL,
            model or DeepSeekClassifier.DEFAULT_MODEL,
            session,
            api_key,
        )
    return KeywordClassifier()
