"""Check the setup before a real run:  python -m triage.doctor

Verifies .env values, Atlassian login, that the Jira project and Confluence space exist,
and (if an LLM is configured) that the model answers.
"""

import json
import sys

import requests

from .classifier import build_classifier
from .config import load_settings
from .http import make_session
from .jira_client import parse_issue
from .main import SAMPLE_FILE

OK, FAIL, INFO = "[OK]  ", "[FAIL]", "      "


def main() -> int:
    cfg = load_settings()
    problems = 0

    for name in ("jira_base_url", "atlassian_email", "atlassian_api_token"):
        if not getattr(cfg, name):
            print(f"{FAIL} {name.upper()} is empty in .env")
            problems += 1
    if problems:
        return 1

    s = make_session(cfg.atlassian_email, cfg.atlassian_api_token)

    # 1. Login
    try:
        r = s.get(f"{cfg.jira_base_url}/rest/api/3/myself")
        r.raise_for_status()
        print(f"{OK} Logged in to {cfg.jira_base_url} as {r.json().get('displayName')}")
    except requests.RequestException as exc:
        print(f"{FAIL} Login failed: {exc}")
        print(f"{INFO} Check JIRA_BASE_URL (https://<site>.atlassian.net), ATLASSIAN_EMAIL and the API token.")
        return 1

    # 2. Jira project
    r = s.get(f"{cfg.jira_base_url}/rest/api/3/project/search", params={"maxResults": 50})
    r.raise_for_status()
    projects = {p["key"]: p["name"] for p in r.json().get("values", [])}
    if cfg.jira_project in projects:
        print(f"{OK} Jira project {cfg.jira_project} ({projects[cfg.jira_project]})")
    else:
        problems += 1
        print(f"{FAIL} Jira project '{cfg.jira_project}' not found. Set JIRA_PROJECT to one of:")
        for key, name in projects.items():
            print(f"{INFO}   {key:<10} {name}")

    # 3. Confluence space
    try:
        r = s.get(f"{cfg.jira_base_url}/wiki/api/v2/spaces", params={"limit": 50})
        r.raise_for_status()
        spaces = {sp["key"]: sp["name"] for sp in r.json().get("results", [])}
        if cfg.confluence_space_key in spaces:
            print(f"{OK} Confluence space {cfg.confluence_space_key} ({spaces[cfg.confluence_space_key]})")
        else:
            problems += 1
            key = cfg.confluence_space_key
            print(f"{FAIL} Confluence space '{key}' not found. Set CONFLUENCE_SPACE_KEY to one of:")
            for key, name in spaces.items():
                print(f"{INFO}   {key:<10} {name}")
    except requests.RequestException as exc:
        problems += 1
        print(f"{FAIL} Confluence not reachable: {exc}")

    # 4. Model
    if cfg.classifier == "keyword":
        print(f"{OK} Classifier: keyword (no AI)")
    else:
        try:
            clf = build_classifier(cfg.classifier, cfg.llm_base_url, cfg.llm_model, cfg.llm_api_key, make_session())
            issue = parse_issue(json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))["issues"][2])
            result = clf.classify(issue)
            if result.source == clf.name:
                print(f"{OK} {clf.name} answered: {result.category} ({result.confidence:.0%}) - {result.summary}")
            else:
                problems += 1
                print(f"{FAIL} {clf.name} did not give a usable answer (see the warning above)")
        except ValueError as exc:
            problems += 1
            print(f"{FAIL} {exc}")

    print("\nAll good - next: python -m triage.seed" if not problems else f"\n{problems} problem(s) to fix in .env")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
