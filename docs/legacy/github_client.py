import os
"""
GitHub Client - Full REST API integration
Uses only urllib (no dependencies)
"""
import json
import logging
import sys
import urllib.request
import urllib.error
import ssl
import base64
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("integration.github")


GITHUB_API = "https://api.github.com"


class GitHubError(Exception):
    pass


class GitHubClient:
    def __init__(self, token: str = "", owner: str = ""):
        self.token = token
        self.owner = owner
        self._ssl_ctx = ssl.create_default_context()

    def _request(self, method: str, path: str,
                 body: Optional[Dict] = None,
                 timeout: int = 20) -> Dict:
        """Makes an authenticated API request."""
        url = path if path.startswith("http") else GITHUB_API + path

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "NovaMind/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data,
                                     headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=self._ssl_ctx) as resp:
                raw = resp.read().decode("utf-8")
                return {
                    "ok": True,
                    "status": resp.status,
                    "data": json.loads(raw) if raw else {},
                }
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")[:300]
            except Exception:
                pass
            return {
                "ok": False,
                "status": e.code,
                "error": f"HTTP {e.code}: {err_body}",
            }
        except urllib.error.URLError as e:
            return {
                "ok": False,
                "status": 0,
                "error": "URL: " + str(e.reason)[:200],
            }
        except Exception as e:
            return {
                "ok": False,
                "status": 0,
                "error": str(e)[:200],
            }

    # ─── User ────────────────────────────────────────
    def get_user(self) -> Dict:
        """Returns authenticated user."""
        return self._request("GET", "/user")

    # ─── Repos ───────────────────────────────────────
    def list_repos(self, limit: int = 30) -> Dict:
        return self._request("GET",
            "/user/repos?per_page=" + str(limit) + "&sort=updated")

    def get_repo(self, full_name: str) -> Dict:
        """full_name = 'owner/repo'"""
        return self._request("GET", "/repos/" + full_name)

    # ─── Files ───────────────────────────────────────
    def get_file(self, repo: str, path: str,
                 branch: str = "main") -> Dict:
        """Reads a file from a repo."""
        result = self._request(
            "GET",
            f"/repos/{repo}/contents/{path}?ref={branch}"
        )
        if not result.get("ok"):
            return result

        data = result["data"]
        content_b64 = data.get("content", "").replace("\n", "")
        try:
            content = base64.b64decode(content_b64).decode("utf-8")
        except Exception:
            content = ""

        return {
            "ok": True,
            "path": path,
            "sha": data.get("sha", ""),
            "content": content,
            "size": data.get("size", 0),
        }

    def create_or_update_file(self, repo: str, path: str,
                              content: str, message: str,
                              branch: str = "main",
                              sha: Optional[str] = None) -> Dict:
        """Creates or updates a file in a repo."""
        body = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        return self._request(
            "PUT",
            f"/repos/{repo}/contents/{path}",
            body=body,
        )

    # ─── Branches ────────────────────────────────────
    def create_branch(self, repo: str, new_branch: str,
                      from_branch: str = "main") -> Dict:
        """Creates a new branch from an existing one."""
        # Get base SHA
        ref = self._request("GET",
            f"/repos/{repo}/git/ref/heads/{from_branch}")
        if not ref.get("ok"):
            return ref

        sha = ref["data"]["object"]["sha"]

        return self._request(
            "POST",
            f"/repos/{repo}/git/refs",
            body={
                "ref": f"refs/heads/{new_branch}",
                "sha": sha,
            },
        )

    # ─── Issues ──────────────────────────────────────
    def list_issues(self, repo: str, state: str = "open",
                    limit: int = 20) -> Dict:
        return self._request(
            "GET",
            f"/repos/{repo}/issues?state={state}&per_page={limit}"
        )

    def create_issue(self, repo: str, title: str, body: str = "",
                     labels: Optional[List[str]] = None) -> Dict:
        payload = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return self._request("POST", f"/repos/{repo}/issues",
                             body=payload)

    def add_comment(self, repo: str, issue_number: int,
                    body: str) -> Dict:
        return self._request(
            "POST",
            f"/repos/{repo}/issues/{issue_number}/comments",
            body={"body": body},
        )

    # ─── Pull Requests ───────────────────────────────
    def create_pr(self, repo: str, title: str, body: str,
                  head: str, base: str = "main") -> Dict:
        return self._request(
            "POST",
            f"/repos/{repo}/pulls",
            body={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            },
        )

    def get_pr(self, repo: str, pr_number: int) -> Dict:
        return self._request("GET", f"/repos/{repo}/pulls/{pr_number}")

    def list_pr_files(self, repo: str, pr_number: int) -> Dict:
        return self._request(
            "GET",
            f"/repos/{repo}/pulls/{pr_number}/files"
        )

    def post_pr_comment(self, repo: str, pr_number: int,
                        body: str) -> Dict:
        """Posts a general comment on a PR (not line-specific)."""
        return self._request(
            "POST",
            f"/repos/{repo}/issues/{pr_number}/comments",
            body={"body": body},
        )

    def post_pr_review(self, repo: str, pr_number: int,
                       body: str, event: str = "COMMENT") -> Dict:
        """event: COMMENT | APPROVE | REQUEST_CHANGES"""
        return self._request(
            "POST",
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            body={"body": body, "event": event},
        )


# Singleton
_client: Optional[GitHubClient] = None


def get_github() -> GitHubClient:
    """Returns GitHub client (loads token from env)."""
    global _client
    if _client is None:
        import os
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        _client = GitHubClient(token=token)
        if token:
            logger.info("GitHub client initialized with token")
        else:
            logger.warning("GitHub client: no token (public access only)")
    return _client


github = get_github()
