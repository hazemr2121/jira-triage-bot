import pytest

from triage.classifier import DeepSeekClassifier, KeywordClassifier, OllamaClassifier, build_classifier
from triage.http import make_session


def test_deepseek_uses_defaults():
    clf = build_classifier("deepseek", "", "", "sk-test", make_session())
    assert isinstance(clf, DeepSeekClassifier)
    assert clf.base_url == "https://api.deepseek.com" and clf.model == "deepseek-flash"


def test_deepseek_without_key_fails_fast():
    with pytest.raises(ValueError):
        build_classifier("deepseek", "", "", "", make_session())


def test_deepseek_sends_bearer_key(monkeypatch):
    clf = build_classifier("deepseek", "", "", "sk-test", make_session())
    sent = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"category":"bug","summary":"s","confidence":0.9}'}}]}

    def fake_post(url, **kwargs):
        sent["url"], sent["headers"], sent["json"] = url, kwargs["headers"], kwargs["json"]
        return FakeResp()

    monkeypatch.setattr(clf.session, "post", fake_post)
    assert clf.call_model("Return JSON").startswith("{")
    assert sent["url"] == "https://api.deepseek.com/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer sk-test"
    assert sent["json"]["response_format"] == {"type": "json_object"}


def test_other_kinds():
    assert isinstance(build_classifier("ollama", "", "", "", make_session()), OllamaClassifier)
    assert isinstance(build_classifier("keyword", "", "", "", make_session()), KeywordClassifier)
