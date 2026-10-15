"""GitHub adapter for the autopilot SCM layer (read-only, Slice 1).

Absorbs the legacy root ``github_client.py``: same urllib-only philosophy, but
returns typed :class:`~...base.Issue` / :class:`~...base.Change` objects and
raises typed errors instead of ``{"ok": False}`` result dicts.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from .base import (
    Change,
    Issue,
    Response,
    Transport,
    as_int,
    label_names,
    normalize_state,
    retry_after_seconds,
)
from .exceptions import TransientError, error_for_status
from .transport import UrllibTransport

__all__ = ["GitHubSCM", "GITHUB_API"]

logger = logging.getLogger("novamind.autopilot.scm")

GITHUB_API = "https://api.github.com"
_API_VERSION = "2022-11-28"
_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="([^"]+)"')


def _next_link(link_header: str) -> str:
    """Return the ``rel="next"`` URL from a GitHub ``Link`` header, or ``""``."""
    for url, rel in _LINK_RE.findall(link_header or ""):
        if rel == "next":
            return url
    return ""


class GitHubSCM:
    """Read-only GitHub REST client.

    ``repo`` is the ``"owner/name"`` slug. A ``transport`` may be injected for
    tests; by default an :class:`UrllibTransport` talks to the real API.
    """

    platform = "github"

    def __init__(
        self,
        token: str = "",
        *,
        repo: str = "",
        transport: Optional[Transport] = None,
        base_url: str = GITHUB_API,
        timeout: float = 20.0,
        per_page: int = 50,
    ) -> None:
        self.token = token
        self.repo = repo.strip("/")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.per_page = per_page
        self._transport: Transport = transport or UrllibTransport(timeout=timeout)

    # ── plumbing ─────────────────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "nexus-core-autopilot",
            "X-GitHub-Api-Version": _API_VERSION,
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return headers

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return self.base_url + path

    def _send(self, url: str) -> Response:
        logger.debug("GET %s", self._url(url))
        return self._transport.request(
            "GET", self._url(url), headers=self._headers(), timeout=self.timeout
        )

    @staticmethod
    def _check(resp: Response) -> Response:
        if 200 <= resp.status < 300:
            return resp
        detail = resp.body.decode("utf-8", "replace")[:300] if resp.body else ""
        logger.warning("github request failed: HTTP %s", resp.status)
        raise error_for_status(
            resp.status, detail, retry_after=retry_after_seconds(resp.headers)
        )

    @staticmethod
    def _json(resp: Response) -> Any:
        try:
            return json.loads(resp.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError) as exc:
            raise TransientError("malformed response body", status=0) from exc

    def _paged(self, path: str, limit: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url = path
        while url and len(items) < limit:
            resp = self._check(self._send(url))
            data = self._json(resp)
            if not isinstance(data, list):
                break
            items.extend(item for item in data if isinstance(item, dict))
            url = _next_link(resp.headers.get("Link", ""))
        return items[:limit]

    # ── reads ────────────────────────────────────────────────────────────────
    def whoami(self) -> str:
        """Return the login of the authenticated user."""
        data = self._json(self._check(self._send("/user")))
        return str(data.get("login", ""))

    def list_issues(
        self,
        *,
        labels: tuple[str, ...] = (),
        state: str = "open",
        limit: int = 20,
    ) -> list[Issue]:
        """Return open/closed issues; pull requests are excluded."""
        query = f"/repos/{self.repo}/issues?state={state}&per_page={self.per_page}"
        if labels:
            query += "&labels=" + ",".join(labels)
        return [self._issue(item) for item in self._paged(query, limit) if "pull_request" not in item]

    def get_issue(self, number: int) -> Issue:
        """Return a single issue by number."""
        return self._issue(self._json(self._check(self._send(f"/repos/{self.repo}/issues/{number}"))))

    def list_changes(self, *, state: str = "open", limit: int = 20) -> list[Change]:
        """Return pull requests."""
        path = f"/repos/{self.repo}/pulls?state={state}&per_page={self.per_page}"
        return [self._change(item) for item in self._paged(path, limit)]

    def get_change(self, number: int) -> Change:
        """Return a single pull request by number."""
        return self._change(
            self._json(self._check(self._send(f"/repos/{self.repo}/pulls/{number}")))
        )

    # ── mapping ──────────────────────────────────────────────────────────────
    def _issue(self, data: dict[str, Any]) -> Issue:
        return Issue(
            platform=self.platform,
            id=as_int(data.get("id")),
            number=as_int(data.get("number")),
            title=str(data.get("title", "")),
            body=str(data.get("body") or ""),
            state=normalize_state(str(data.get("state", ""))),
            labels=label_names(data.get("labels")),
            author=str((data.get("user") or {}).get("login", "")),
            url=str(data.get("html_url", "")),
        )

    def _change(self, data: dict[str, Any]) -> Change:
        return Change(
            platform=self.platform,
            id=as_int(data.get("id")),
            number=as_int(data.get("number")),
            title=str(data.get("title", "")),
            body=str(data.get("body") or ""),
            state=normalize_state(str(data.get("state", ""))),
            head=str((data.get("head") or {}).get("ref", "")),
            base=str((data.get("base") or {}).get("ref", "")),
            author=str((data.get("user") or {}).get("login", "")),
            url=str(data.get("html_url", "")),
        )
