"""Settings come from environment variables (or a local .env file). No secrets in code."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# The fixed set of categories the bot may suggest. Anything else from the LLM is rejected.
CATEGORIES = [
    "access_request",
    "bug",
    "how_to",
    "data_fix",
    "performance",
    "feature_request",
    "other",
]

# Label the bot adds after commenting, so the same ticket is never processed twice.
BOT_LABEL = "triage-bot-reviewed"


@dataclass
class Settings:
    jira_base_url: str
    atlassian_email: str
    atlassian_api_token: str
    jira_project: str
    confluence_space_key: str
    classifier: str  # "keyword" | "ollama" | "openai" | "deepseek"
    llm_base_url: str
    llm_model: str
    llm_api_key: str

    @property
    def default_jql(self) -> str:
        # `labels != X` alone skips issues with no labels at all, so EMPTY is needed too.
        return (
            f'project = "{self.jira_project}" AND statusCategory != Done '
            f'AND (labels is EMPTY OR labels != "{BOT_LABEL}") ORDER BY created DESC'
        )


def load_settings() -> Settings:
    env = os.environ.get
    return Settings(
        jira_base_url=env("JIRA_BASE_URL", "").rstrip("/"),
        atlassian_email=env("ATLASSIAN_EMAIL", ""),
        atlassian_api_token=env("ATLASSIAN_API_TOKEN", ""),
        jira_project=env("JIRA_PROJECT", "SUP"),
        confluence_space_key=env("CONFLUENCE_SPACE_KEY", "SUP"),
        classifier=env("CLASSIFIER", "keyword"),
        # Empty means "use the chosen classifier's default".
        llm_base_url=env("LLM_BASE_URL", "").rstrip("/"),
        llm_model=env("LLM_MODEL", ""),
        llm_api_key=env("LLM_API_KEY", ""),
    )
