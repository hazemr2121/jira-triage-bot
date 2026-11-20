# Jira Triage Bot

A small Python tool that helps an application-support team triage tickets:

1. **Fetches** open Jira tickets with JQL (REST API v3, paginated).
2. **Suggests** a category and a one-line summary for each ticket. It can use keyword rules, a local LLM (Ollama), or any OpenAI-compatible API.
3. **Writes back** the suggestion as a Jira **comment** and adds a label. It never changes the ticket's fields; a person makes the final call.
4. **Publishes** a daily summary page to Confluence, and creates or updates it on each run.

```
Jira (JQL) ──► redact PII ──► classifier ──► validate ──► Jira comment + label
                                   │             │
                                   │             └─ rejected? → keyword fallback + "needs review"
                                   └────────────────────────────► Confluence summary page
```

## Quick start (no Jira needed)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m triage.main --offline        # runs on sample_data/issues.json, writes out/report.html
pytest -q
```

## Run against a real Jira + Confluence

1. Create a free Atlassian Cloud site with Jira and Confluence. Add a Jira project with key `SUP` and a Confluence space with key `SUP`.
2. Create an API token at id.atlassian.com → Security → API tokens.
3. `cp .env.example .env` and fill it in.
4. Check the setup. This verifies the login and the project and space keys, and lists the right keys if yours are wrong:

```bash
python -m triage.doctor
```

5. On a brand-new site, create the 7 sample tickets (labelled `triage-demo`; re-running won't duplicate them):

```bash
python -m triage.seed
```

6. Run it:

```bash
python -m triage.main                    # dry run: prints suggestions, changes nothing
python -m triage.main --apply            # comments + labels the tickets
python -m triage.main --apply --publish  # ...and publishes the Confluence page
python -m triage.main --jql 'project = SUP AND priority = High'
```

**Choosing the model** (`CLASSIFIER` in `.env`, or `--classifier` on the command line):

| Value | What it uses |
|---|---|
| `deepseek` | DeepSeek API (OpenAI-compatible, `https://api.deepseek.com`, model `deepseek-flash`). Needs `LLM_API_KEY`. |
| `ollama` | A local model (`ollama pull llama3.2`), so no data leaves the machine. |
| `openai` | Any OpenAI-compatible endpoint. Set `LLM_BASE_URL` and `LLM_MODEL`. |
| `keyword` | No AI: rules only. This is also the fallback when a model's answer is rejected. |

Try DeepSeek on the sample tickets without touching Jira:

```bash
python -m triage.main --offline --classifier deepseek
```

## Design decisions

| Decision | Why |
|---|---|
| **Dry run by default** | Writing to tickets needs an explicit `--apply`, so a test run can't change production data. |
| **Comment, don't edit** | The bot only suggests. An agent confirms or corrects it, which keeps a human in the loop. |
| **PII redaction before the LLM** | Emails, phone numbers, national IDs and card or account numbers are masked before any text reaches a model. |
| **Local model option (Ollama)** | Ticket data can stay on the bank's own servers. |
| **Validate LLM output** | It must be JSON, the category must be in a fixed list, and the confidence must be 0–1. Anything else falls back to keywords and is flagged for review. LLMs can hallucinate, so their output isn't trusted blindly. |
| **Label = idempotency** | The default JQL skips tickets that already have the `triage-bot-reviewed` label, so re-running never double-comments. The label is added *after* the comment, so if commenting fails, the ticket is retried on the next run. |
| **`labels is EMPTY OR labels != X`** | In JQL, `labels != X` on its own silently skips tickets that have no labels at all. |
| **Retries with backoff, GET/PUT only** | It retries on 429 and 5xx and respects `Retry-After`. POST isn't retried, because a retried POST could create a duplicate comment. |
| **Timeouts on every request** | A hung server can't hang the job. |
| **Per-ticket error handling** | One failed ticket is logged and the run continues. The exit code is 1 if anything failed, so a scheduler notices. |
| **Secrets in `.env`** | Never in code, and `.env` is in `.gitignore`. |
| **CI** | GitHub Actions runs lint, tests and an offline smoke run on every push. |

## Project layout

```
triage/
  config.py             settings from env, category list, default JQL
  http.py               shared session: timeout, retries, auth
  jira_client.py        JQL search (nextPageToken), comment, label, ADF <-> text
  confluence_client.py  create-or-update page (API v2, storage format)
  classifier.py         redaction, keyword / Ollama / OpenAI classifiers, output validation
  report.py             comment text + HTML page (escaped)
  main.py               CLI
  doctor.py             setup check: login, project/space keys, model
  seed.py               create sample tickets in a new Jira project
tests/                  21 tests: classification, redaction, LLM fallback, JQL, HTML escaping
sample_data/            7 realistic tickets for offline demos
```

## Ideas for next steps

- Run it on a schedule (cron, Jira Automation calling a webhook, n8n, or Airflow).
- Measure accuracy: compare the bot's category with the one the agent finally chose.
- Use RAG over Confluence troubleshooting pages to suggest a likely fix, not just a category.
