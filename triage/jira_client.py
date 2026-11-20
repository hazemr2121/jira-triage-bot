"""Thin wrapper over the Jira Cloud REST API v3."""

import logging
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)


@dataclass
class Issue:
    key: str
    summary: str
    description: str
    status: str
    priority: str
    labels: list[str]


def adf_to_text(node) -> str:
    """Jira v3 returns descriptions in Atlassian Document Format (nested JSON). Flatten it to text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if node.get("type") == "text":
        return node.get("text", "")
    parts = [adf_to_text(child) for child in node.get("content", [])]
    separator = "\n" if node.get("type") in ("doc", "bulletList", "orderedList") else ""
    return separator.join(parts) + ("\n" if node.get("type") == "paragraph" else "")


def parse_issue(raw: dict) -> Issue:
    fields = raw.get("fields", {})
    return Issue(
        key=raw["key"],
        summary=fields.get("summary") or "",
        description=adf_to_text(fields.get("description")).strip(),
        status=(fields.get("status") or {}).get("name", ""),
        priority=(fields.get("priority") or {}).get("name", ""),
        labels=fields.get("labels") or [],
    )


def text_to_adf(text: str) -> dict:
    """Wrap plain text lines as an ADF document (needed when posting comments)."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            for line in text.splitlines()
            if line.strip()
        ],
    }


class JiraClient:
    def __init__(self, base_url: str, session: requests.Session):
        self.base_url = base_url
        self.session = session

    def search(self, jql: str, max_issues: int = 50) -> list[Issue]:
        """Run JQL using the enhanced search endpoint, following nextPageToken pagination."""
        issues: list[Issue] = []
        token = None
        while len(issues) < max_issues:
            params = {
                "jql": jql,
                "fields": "summary,description,status,priority,labels",
                "maxResults": min(50, max_issues - len(issues)),
            }
            if token:
                params["nextPageToken"] = token
            resp = self.session.get(f"{self.base_url}/rest/api/3/search/jql", params=params)
            resp.raise_for_status()
            data = resp.json()
            issues += [parse_issue(raw) for raw in data.get("issues", [])]
            token = data.get("nextPageToken")
            if data.get("isLast", True) or not token:
                break
        log.info("JQL returned %d issue(s)", len(issues))
        return issues

    def add_comment(self, key: str, text: str) -> None:
        resp = self.session.post(
            f"{self.base_url}/rest/api/3/issue/{key}/comment", json={"body": text_to_adf(text)}
        )
        resp.raise_for_status()

    def add_label(self, key: str, label: str) -> None:
        resp = self.session.put(
            f"{self.base_url}/rest/api/3/issue/{key}",
            json={"update": {"labels": [{"add": label}]}},
        )
        resp.raise_for_status()
