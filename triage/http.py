"""One shared HTTP session: timeouts, retries with backoff, and basic auth."""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15


class TimeoutSession(requests.Session):
    """A Session that always sets a timeout, so a hung server can't hang the bot."""

    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT_SECONDS)
        return super().request(*args, **kwargs)


def make_session(email: str = "", api_token: str = "") -> requests.Session:
    retry = Retry(
        total=4,
        backoff_factor=1,  # waits 1s, 2s, 4s, 8s between attempts
        status_forcelist=[429, 500, 502, 503, 504],
        respect_retry_after_header=True,  # Atlassian sends Retry-After on 429
        # Default allowed_methods excludes POST: retrying a POST could create a duplicate comment.
    )
    session = TimeoutSession()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers.update({"Accept": "application/json"})
    if email and api_token:
        session.auth = (email, api_token)  # Atlassian Cloud: email + API token as basic auth
    return session
