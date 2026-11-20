"""Create the sample tickets in your own Jira project, for a demo:  python -m triage.seed

Seeded tickets get the label `triage-demo`, and seeding is skipped if they already exist,
so running it twice doesn't create duplicates. Use --force to seed again anyway.
"""

import argparse
import json
import logging
import sys

import requests

from .config import load_settings
from .http import make_session
from .main import SAMPLE_FILE

log = logging.getLogger("triage.seed")
DEMO_LABEL = "triage-demo"


def pick_issue_type(session: requests.Session, base_url: str, project: str) -> dict:
    """Prefer 'Task'; otherwise the first standard (non-subtask, non-epic) type the project has."""
    r = session.get(f"{base_url}/rest/api/3/issue/createmeta/{project}/issuetypes")
    r.raise_for_status()
    types = [t for t in r.json().get("issueTypes", r.json().get("values", [])) if not t.get("subtask")]
    for preferred in ("Task", "Bug", "Story"):
        for t in types:
            if t["name"] == preferred:
                return t
    types = [t for t in types if t["name"] != "Epic"] or types
    if not types:
        raise RuntimeError(f"Project {project} has no issue types you can create")
    return types[0]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Create sample tickets in Jira")
    p.add_argument("--force", action="store_true", help="Seed even if demo tickets already exist")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    cfg = load_settings()
    s = make_session(cfg.atlassian_email, cfg.atlassian_api_token)
    base = cfg.jira_base_url

    try:
        r = s.get(
            f"{base}/rest/api/3/search/jql",
            params={"jql": f'project = "{cfg.jira_project}" AND labels = "{DEMO_LABEL}"', "maxResults": 1},
        )
        r.raise_for_status()
        if r.json().get("issues") and not args.force:
            log.info("Demo tickets already exist in %s - skipping (use --force to add more)", cfg.jira_project)
            return 0

        issue_type = pick_issue_type(s, base, cfg.jira_project)
        log.info("Creating tickets in %s as issue type '%s'", cfg.jira_project, issue_type["name"])

        samples = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))["issues"]
        use_labels = True
        for sample in samples:
            fields = {
                "project": {"key": cfg.jira_project},
                "issuetype": {"id": issue_type["id"]},
                "summary": sample["fields"]["summary"],
                "description": sample["fields"]["description"],
            }
            if use_labels:
                fields["labels"] = [DEMO_LABEL]
            r = s.post(f"{base}/rest/api/3/issue", json={"fields": fields})
            if r.status_code == 400 and use_labels and "labels" in r.text:
                # Some project layouts don't allow labels on create; carry on without them.
                log.warning("This project doesn't accept labels on create; seeding without them")
                use_labels = False
                fields.pop("labels")
                r = s.post(f"{base}/rest/api/3/issue", json={"fields": fields})
            if not r.ok:
                log.error("Failed to create '%s': %s %s", fields["summary"], r.status_code, r.text[:300])
                return 1
            log.info("Created %s  %s", r.json()["key"], fields["summary"])
    except (requests.RequestException, RuntimeError) as exc:
        log.error("%s", exc)
        return 1

    log.info("Done. Next: python -m triage.main   (dry run first)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
