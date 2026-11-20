"""Create or update one Confluence page (Confluence Cloud REST API v2)."""

import logging

import requests

log = logging.getLogger(__name__)


class ConfluenceClient:
    def __init__(self, base_url: str, session: requests.Session):
        self.api = f"{base_url}/wiki/api/v2"
        self.session = session

    def space_id(self, space_key: str) -> str:
        resp = self.session.get(f"{self.api}/spaces", params={"keys": space_key})
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            raise ValueError(f"Confluence space '{space_key}' not found or no access")
        return results[0]["id"]

    def upsert_page(self, space_key: str, title: str, html: str) -> str:
        """Update the page if one with this title exists, otherwise create it. Returns the page id."""
        space_id = self.space_id(space_key)
        body = {"representation": "storage", "value": html}

        resp = self.session.get(
            f"{self.api}/pages", params={"space-id": space_id, "title": title}
        )
        resp.raise_for_status()
        existing = resp.json().get("results", [])

        if existing:
            page_id = existing[0]["id"]
            version = existing[0]["version"]["number"]
            resp = self.session.put(
                f"{self.api}/pages/{page_id}",
                json={
                    "id": page_id,
                    "status": "current",
                    "title": title,
                    "body": body,
                    "version": {"number": version + 1, "message": "Updated by triage bot"},
                },
            )
            resp.raise_for_status()
            log.info("Updated Confluence page %s", page_id)
            return page_id

        resp = self.session.post(
            f"{self.api}/pages",
            json={"spaceId": space_id, "status": "current", "title": title, "body": body},
        )
        resp.raise_for_status()
        page_id = resp.json()["id"]
        log.info("Created Confluence page %s", page_id)
        return page_id
