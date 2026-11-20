"""CLI entry point.

  python -m triage.main --offline                  # demo with sample tickets, no network
  python -m triage.main                            # read real Jira, print suggestions (dry run)
  python -m triage.main --apply --publish          # comment + label tickets, publish Confluence page
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import requests

from .classifier import build_classifier
from .config import BOT_LABEL, load_settings
from .confluence_client import ConfluenceClient
from .http import make_session
from .jira_client import JiraClient, parse_issue
from .report import comment_text, page_html, page_title

log = logging.getLogger("triage")
SAMPLE_FILE = Path(__file__).resolve().parent.parent / "sample_data" / "issues.json"
OUT_DIR = Path("out")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Suggest categories for open Jira tickets.")
    p.add_argument("--jql", help="Override the default JQL query")
    p.add_argument("--max", type=int, default=50, help="Max tickets to process (default 50)")
    p.add_argument("--offline", action="store_true", help="Use sample_data/issues.json")
    p.add_argument("--apply", action="store_true", help="Post comments and add the bot label")
    p.add_argument("--publish", action="store_true", help="Publish the summary to Confluence")
    p.add_argument(
        "--classifier", choices=["keyword", "ollama", "openai", "deepseek"], help="Override CLASSIFIER"
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    cfg = load_settings()
    if args.classifier:
        cfg.classifier = args.classifier

    if args.offline and (args.apply or args.publish):
        log.error("--offline can't be combined with --apply or --publish")
        return 2
    if not args.offline and not (cfg.jira_base_url and cfg.atlassian_api_token):
        log.error("Set JIRA_BASE_URL, ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN (see .env.example)")
        return 2

    atlassian = make_session(cfg.atlassian_email, cfg.atlassian_api_token)
    jira = JiraClient(cfg.jira_base_url, atlassian)
    try:
        classifier = build_classifier(
            cfg.classifier, cfg.llm_base_url, cfg.llm_model, cfg.llm_api_key, make_session()
        )
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    log.info("Classifier: %s | mode: %s", classifier.name, "APPLY" if args.apply else "dry run")

    # 1. Fetch
    try:
        if args.offline:
            raw = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
            issues = [parse_issue(i) for i in raw["issues"]][: args.max]
        else:
            issues = jira.search(args.jql or cfg.default_jql, args.max)
    except requests.RequestException as exc:
        log.error("Could not fetch tickets: %s", exc)
        return 1

    # 2. Classify + (optionally) write back, one ticket at a time so one failure doesn't stop the run
    results, failed = [], []
    for issue in issues:
        suggestion = classifier.classify(issue)
        results.append((issue, suggestion))
        flag = " [REVIEW]" if suggestion.needs_human else ""
        print(f"{issue.key:<8} {suggestion.category:<16} {suggestion.confidence:>4.0%}{flag}  {issue.summary}")

        if args.apply:
            try:
                jira.add_comment(issue.key, comment_text(suggestion))
                jira.add_label(issue.key, BOT_LABEL)  # label last: if commenting fails, we retry next run
            except requests.RequestException as exc:
                log.error("%s: write-back failed: %s", issue.key, exc)
                failed.append(issue.key)

    # 3. Report
    html = page_html(results, "" if args.offline else cfg.jira_base_url)
    OUT_DIR.mkdir(exist_ok=True)
    local = OUT_DIR / "report.html"
    local.write_text(f"<html><body><h1>{page_title(cfg.jira_project)}</h1>{html}</body></html>", encoding="utf-8")
    log.info("Wrote %s", local)

    if args.publish:
        try:
            ConfluenceClient(cfg.jira_base_url, atlassian).upsert_page(
                cfg.confluence_space_key, page_title(cfg.jira_project), html
            )
        except (requests.RequestException, ValueError) as exc:
            log.error("Confluence publish failed: %s", exc)
            return 1

    review = sum(s.needs_human for _, s in results)
    log.info("Done: %d ticket(s), %d need review, %d write-back failure(s)", len(results), review, len(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
