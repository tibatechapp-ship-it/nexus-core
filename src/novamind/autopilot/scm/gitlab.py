"""GitLab adapter for the autopilot SCM layer (read-only, Slice 1).

Mirrors :class:`~...scm.github.GitHubSCM` behind the same neutral interface so
every autopilot worker runs unchanged on GitLab. GitLab calls pull requests
*merge requests*, and labels issues/MRs with ``iid`` (per-project number); both
differences are absorbed here.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import quote

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

__all__ = ["GitLabSCM", "GITLAB_BASE"]

GITLAB_BASE = "https://gitlab.com"
_API = "/api/v4"
_STATE_TO_GITLAB = {"open": "opened"}


class GitLabSCM:
    """Read-only GitLab REST client.

    ``project`` is either a numeric project id or a ``"group/project"`` path.
    A ``transport`` may be injected for tests; by default an
    :class:`UrllibTransport` talks to the real API.
    """

    platform = "gitlab"

    def __init__(
        self,
        token: str = "",
        *,
        project: str = "",
        transport: Optional[Transport] = None,
        base_url: str = GITLAB_BASE,
        timeout: float = 20.0,
        per_page: int = 50,
    ) -> None:
        self.token = token
        self.project = project.strip("/")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.per_page = per_page
        self._transport: Transport = transport or UrllibTransport(timeout=timeout)

    # ── plumbing ─────────────────────────────────────────────────────────────
    def _project_id(self) -> str:
        if self.project.isdigit():
            return self.project
        return quote(self.project, safe="")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "nexus-core-autopilot"}
        if self.token:
            headers["PRIVATE-TOKEN"] = self.token
        return headers

    def _base(self) -> str:
        return f"{self.base_url}{_API}/projects/{self._project_id()}"

    def _send(self, url: str) -> Response:
        return self._transport.request(
            "GET", self.base_url + url, headers=self._headers(), timeout=self.timeout
        )

    @staticmethod
    def _check(resp: Response) -> Response:
        if 200 <= resp.status < 300:
            return resp
        detail = resp.body.decode("utf-8", "replace")[:300] if resp.body else ""
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
        page = 1
        while page and len(items) < limit:
            sep = "&" if "?" in path else "?"
            url = f"{path}{sep}per_page={self.per_page}&page={page}"
            resp = self._check(self._send(url))
            data = self._json(resp)
            if not isinstance(data, list):
                break
            items.extend(item for item in data if isinstance(item, dict))
            next_page = resp.headers.get("X-Next-Page", "")
            page = int(next_page) if next_page.isdigit() else 0
        return items[:limit]

    # ── reads ────────────────────────────────────────────────────────────────
    def whoami(self) -> str:
        """Return the username of the authenticated user."""
        data = self._json(self._check(self._send("/api/v4/user")))
        return str(data.get("username", ""))

    def list_issues(
        self,
        *,
        labels: tuple[str, ...] = (),
        state: str = "open",
        limit: int = 20,
    ) -> list[Issue]:
        """Return issues; ``state`` is normalised (``open`` → ``opened``)."""
        gl_state = _STATE_TO_GITLAB.get(state, state)
        path = f"{self._base()}/issues?state={gl_state}"
        if labels:
            path += "&labels=" + ",".join(labels)
        return [self._issue(item) for item in self._paged(path, limit)]

    def get_issue(self, number: int) -> Issue:
        """Return a single issue by its per-project ``iid``."""
        return self._issue(
            self._json(self._check(self._send(f"{self._base()}/issues/{number}")))
        )

    def list_changes(self, *, state: str = "open", limit: int = 20) -> list[Change]:
        """Return merge requests."""
        gl_state = _STATE_TO_GITLAB.get(state, state)
        path = f"{self._base()}/merge_requests?state={gl_state}"
        return [self._change(item) for item in self._paged(path, limit)]

    def get_change(self, number: int) -> Change:
        """Return a single merge request by its per-project ``iid``."""
        return self._change(
            self._json(self._check(self._send(f"{self._base()}/merge_requests/{number}")))
        )

    # ── mapping ──────────────────────────────────────────────────────────────
    def _issue(self, data: dict[str, Any]) -> Issue:
        return Issue(
            platform=self.platform,
            id=as_int(data.get("id")),
            number=as_int(data.get("iid")),
            title=str(data.get("title", "")),
            body=str(data.get("description") or ""),
            state=normalize_state(str(data.get("state", ""))),
            labels=label_names(data.get("labels")),
            author=str((data.get("author") or {}).get("username", "")),
            url=str(data.get("web_url", "")),
        )

    def _change(self, data: dict[str, Any]) -> Change:
        return Change(
            platform=self.platform,
            id=as_int(data.get("id")),
            number=as_int(data.get("iid")),
            title=str(data.get("title", "")),
            body=str(data.get("description") or ""),
            state=normalize_state(str(data.get("state", ""))),
            head=str(data.get("source_branch", "")),
            base=str(data.get("target_branch", "")),
            author=str((data.get("author") or {}).get("username", "")),
            url=str(data.get("web_url", "")),
        )
