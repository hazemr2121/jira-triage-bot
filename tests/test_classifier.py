import pytest

from triage.classifier import KeywordClassifier, OllamaClassifier, redact, validate
from triage.http import make_session
from triage.jira_client import Issue


def issue(summary, description=""):
    return Issue("SUP-1", summary, description, "To Do", "Medium", [])


@pytest.mark.parametrize(
    "summary, expected",
    [
        ("Account locked, need access", "access_request"),
        ("Report page is slow and hits a timeout", "performance"),
        ("Export fails with error 500", "bug"),
        ("How do I change my signature?", "how_to"),
    ],
)
def test_keyword_categories(summary, expected):
    assert KeywordClassifier().classify(issue(summary)).category == expected


def test_no_keywords_goes_to_human():
    s = KeywordClassifier().classify(issue("Printer on 3rd floor"))
    assert s.category == "other" and s.needs_human


def test_redact_removes_personal_data():
    text = "mail a.b@bank.com, phone 01012345678, card 4111 1111 1111 1111, id 29801011234567"
    out = redact(text)
    for secret in ["a.b@bank.com", "01012345678", "4111 1111", "29801011234567"]:
        assert secret not in out


def test_validate_accepts_good_output():
    s = validate('{"category": "bug", "summary": "Export breaks", "confidence": 0.9}', "test")
    assert s.category == "bug" and not s.needs_human


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"category": "hack_the_bank", "summary": "x", "confidence": 0.9}',
        '{"category": "bug", "summary": "", "confidence": 0.9}',
        '{"category": "bug", "summary": "x", "confidence": 7}',
    ],
)
def test_validate_rejects_bad_output(raw):
    with pytest.raises(ValueError):
        validate(raw, "test")


def test_llm_garbage_falls_back_to_keywords(monkeypatch):
    clf = OllamaClassifier("http://unused", "model", make_session())
    monkeypatch.setattr(clf, "call_model", lambda prompt: "Sure! The category is probably bug.")
    s = clf.classify(issue("Export fails with error 500"))
    assert s.source == "keyword" and s.category == "bug" and s.needs_human


def test_prompt_is_redacted():
    clf = OllamaClassifier("http://unused", "model", make_session())
    prompt = clf.prompt_for(issue("Locked out", "reach me at haz@example.com"))
    assert "haz@example.com" not in prompt and "[EMAIL]" in prompt
