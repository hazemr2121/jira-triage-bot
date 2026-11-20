from triage.classifier import Suggestion
from triage.config import load_settings
from triage.jira_client import Issue, adf_to_text, text_to_adf
from triage.report import comment_text, page_html


def test_adf_round_trip():
    adf = text_to_adf("line one\nline two")
    text = adf_to_text(adf)
    assert "line one" in text and "line two" in text


def test_default_jql_includes_unlabelled_issues():
    jql = load_settings().default_jql
    assert "labels is EMPTY" in jql and "statusCategory != Done" in jql


def test_comment_says_nothing_was_changed():
    text = comment_text(Suggestion("bug", "Export breaks", 0.5, "keyword", True))
    assert "no fields were changed" in text and "Needs human review" in text


def test_page_escapes_html():
    issue = Issue("SUP-9", "<script>alert(1)</script>", "", "To Do", "Low", [])
    html = page_html([(issue, Suggestion("other", "x", 0.2, "keyword", True))])
    assert "<script>" not in html and "&lt;script&gt;" in html
