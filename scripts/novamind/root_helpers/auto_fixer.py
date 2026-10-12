"""
Auto-Fixer - Automatically fixes bugs found in PRs
- Analyzes issues
- Generates fixes
- Creates a new branch
- Opens a PR with the fix
"""
from pathlib import Path
import logging
import sys
from datetime import datetime, timezone
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.safety.code_safety import integrity_check

from integration.github_client import get_github
from agents.multilang_analyzer import multilang_analyzer
from agents.arabic_analyzer import arabic_analyzer
from agents.fixer import fixer
from agents.tester import tester

logger = logging.getLogger("integration.auto_fixer")


class AutoFixer:
    def __init__(self):
        self.gh = get_github()

    def fix_pr_issues(self, repo: str, pr_number: int,
                      dry_run: bool = False) -> Dict:
        """
        Fixes issues in a PR by creating a new PR with fixes.
        """
        logger.info(f"auto-fixing PR {repo}#{pr_number}")

        # 1. Get PR info
        pr = self.gh.get_pr(repo, pr_number)
        if not pr.get("ok"):
            return {"ok": False, "error": "PR fetch failed"}

        head_branch = pr["data"]["head"]["ref"]
        head_sha = pr["data"]["head"]["sha"]
        base_branch = pr["data"]["base"]["ref"]

        # 2. Get files
        files = self.gh.list_pr_files(repo, pr_number)
        if not files.get("ok"):
            return {"ok": False, "error": "Files fetch failed"}

        fixes_made = []
        total_issues = 0

        for f in files["data"]:
            filename = f["filename"]
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

            if ext not in (".py", ".ts", ".tsx", ".js", ".jsx"):
                continue

            # Get file content
            file_result = self.gh.get_file(repo, filename, branch=head_sha)
            if not file_result.get("ok"):
                continue

            code = file_result["content"]

            # 3. Analyze
            analysis = multilang_analyzer.analyze(code, filename)
            arabic_analysis = arabic_analyzer.analyze(code, filename)

            issues = analysis.get("issues", [])
            if arabic_analysis.get("issues"):
                issues += arabic_analysis["issues"]

            total_issues += len(issues)

            if not issues:
                continue

            # 4. Fix (only for Python, others need manual)
            if ext == ".py":
                try:
                    fix_result = fixer.fix(
                        code,
                        error=f"Found {len(issues)} issues",
                        issues=issues[:5],
                    )

                    if fix_result.get("ok") and fix_result.get("code"):
                        fixed_code = fix_result["code"]

                        # Test
                        test = tester.run(fixed_code)
                        if test.get("success"):
                            fixes_made.append({
                                "path": filename,
                                "original": code,
                                "fixed": fixed_code,
                                "issues_fixed": len(issues),
                                "sha": file_result.get("sha", ""),
                            })
                            logger.info(
                                f"fixed {filename}: {len(issues)} issues"
                            )
                        else:
                            logger.warning(
                                f"fix for {filename} failed test"
                            )
                except Exception as e:
                    logger.error(f"fix error on {filename}: {e}")

        if not fixes_made:
            return {
                "ok": True,
                "fixes_count": 0,
                "message": "no fixes were applicable",
                "issues_found": total_issues,
            }

        # 5. Create branch and commit fixes
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "fixes_count": len(fixes_made),
                "issues_found": total_issues,
                "files": [f["path"] for f in fixes_made],
            }

        # Create branch
        branch_name = f"novamind/fix-pr-{pr_number}-{int(datetime.now(timezone.utc).timestamp())}"
        branch_result = self.gh.create_branch(repo, branch_name, from_branch=head_branch)

        if not branch_result.get("ok"):
            return {
                "ok": False,
                "error": "branch creation failed: " + branch_result.get("error", "")[:100],
            }

        # Commit each fixed file
        committed = 0
        for fix in fixes_made:
            commit_result = self.gh.create_or_update_file(
                repo=repo,
                path=fix["path"],
                content=fix["fixed"],
                message=f"Auto-fix: {fix['issues_fixed']} issues in {fix['path']}\n\nGenerated by NovaMind Pro",
                branch=branch_name,
                sha=fix["sha"],
            )
            if commit_result.get("ok"):
                committed += 1
                logger.info(f"committed {fix['path']}")
            else:
                logger.warning(f"commit failed: {fix['path']}")

        # Create PR with fixes
        pr_body = self._format_pr_body(fixes_made, pr_number)
        pr_result = self.gh.create_pr(
            repo=repo,
            title=f"🤖 NovaMind Auto-Fix: PR #{pr_number} issues",
            body=pr_body,
            head=branch_name,
            base=head_branch,
        )

        return {
            "ok": True,
            "fixes_count": len(fixes_made),
            "files_committed": committed,
            "branch": branch_name,
            "new_pr": pr_result.get("data", {}).get("html_url", ""),
            "new_pr_number": pr_result.get("data", {}).get("number"),
        }

    def _format_pr_body(self, fixes: List[Dict], original_pr: int) -> str:
        lines = [
            f"## 🤖 NovaMind Auto-Fix",
            "",
            f"تم توليد هذا PR تلقائياً لإصلاح المشاكل المكتشفة في PR #{original_pr}.",
            "",
            "### الملفات المُصلحة:",
            "",
        ]
        for fix in fixes:
            lines.append(f"- **`{fix['path']}`** — {fix['issues_fixed']} مشكلة")
        lines.append("")
        lines.append("---")
        lines.append("*مدعوم بـ NovaMind Pro — نظام إصلاح ذاتي التعلم*")
        return "\n".join(lines)


auto_fixer = AutoFixer()
