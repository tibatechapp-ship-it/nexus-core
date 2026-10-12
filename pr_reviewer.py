"""
PR Reviewer v3 - With Test Generation + Learning Loop
- Reviews code
- Generates tests
- Opens follow-up PR with tests
- Learns from every review
"""
from pathlib import Path
import logging
import sys
from datetime import datetime, timezone
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integration.github_client import get_github
from agents.multilang_analyzer import multilang_analyzer
from agents.arabic_analyzer import arabic_analyzer
from agents.test_generator import test_generator

try:
    from core.learning_loop import learning_loop
    LEARNING_AVAILABLE = True
except Exception as _e:
    learning_loop = None
    LEARNING_AVAILABLE = False
    print(f"[WARN] learning_loop not available: {_e}")

logger = logging.getLogger("integration.pr_reviewer")

SUPPORTED_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx",
                  ".json", ".yaml", ".yml", ".md"}

TESTABLE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx"}


class PRReviewer:
    def __init__(self):
        self.gh = get_github()

    def review_pr(self, repo: str, pr_number: int,
                  dry_run: bool = False,
                  generate_tests: bool = True) -> Dict:
        """Reviews a PR and optionally generates tests."""
        logger.info(f"reviewing PR {repo}#{pr_number}")

        # 1. Get PR info
        pr = self.gh.get_pr(repo, pr_number)
        if not pr.get("ok"):
            return {"ok": False,
                    "error": "PR fetch failed: " + pr.get("error", "")[:100]}

        head_sha = pr["data"]["head"]["sha"]
        head_branch = pr["data"]["head"]["ref"]

        # 2. Get files
        files = self.gh.list_pr_files(repo, pr_number)
        if not files.get("ok"):
            return {"ok": False, "error": "Files fetch failed"}

        file_list = files["data"]
        logger.info(f"PR has {len(file_list)} changed files")

        # 3. Analyze each file
        issues_total = 0
        review_comments = []
        files_reviewed = 0
        testable_files = []
        all_issues_flat = []

        for f in file_list:
            filename = f["filename"]
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

            if ext not in SUPPORTED_EXTS:
                continue

            file_result = self.gh.get_file(repo, filename, branch=head_sha)
            if not file_result.get("ok"):
                continue

            code = file_result["content"]
            files_reviewed += 1

            try:
                analysis = multilang_analyzer.analyze(code, filename)
                arabic_analysis = arabic_analyzer.analyze(code, filename)

                all_issues = analysis.get("issues", [])
                if arabic_analysis.get("issues"):
                    all_issues += arabic_analysis["issues"]

                verdict = analysis.get("verdict", "?")

                if all_issues:
                    issues_total += len(all_issues)
                    comment = self._format_comment(filename, verdict, all_issues)
                    review_comments.append(comment)

                    # Collect for learning
                    for iss in all_issues:
                        iss_copy = dict(iss)
                        iss_copy["filename"] = filename
                        all_issues_flat.append(iss_copy)

                if ext in TESTABLE_EXTS and code.strip():
                    testable_files.append({
                        "filename": filename,
                        "code": code,
                        "sha": file_result.get("sha", ""),
                        "ext": ext,
                    })
            except Exception as e:
                logger.warning(f"analyzer error on {filename}: {e}")

        # 4. Post review
        if not dry_run and review_comments:
            body = self._format_review(review_comments, files_reviewed)
            self.gh.post_pr_comment(repo, pr_number, body)

        # 4.5 Learn from this review
        if LEARNING_AVAILABLE and all_issues_flat:
            try:
                lr = learning_loop.learn_from_pr_review(repo, pr_number, all_issues_flat)
                logger.info(f"learned {lr.get('learned', 0)} patterns")
            except Exception as _le:
                logger.warning(f"learning failed: {_le}")

        # 5. Generate tests + create follow-up PR
        test_pr_result = None
        if generate_tests and testable_files and not dry_run:
            logger.info(f"generating tests for {len(testable_files)} files")
            test_pr_result = self._create_test_pr(
                repo, pr_number, head_branch, testable_files
            )

        return {
            "ok": True,
            "pr_number": pr_number,
            "files_reviewed": files_reviewed,
            "issues_found": issues_total,
            "comments_posted": len(review_comments) if not dry_run else 0,
            "testable_files": len(testable_files),
            "learned_patterns": len(all_issues_flat) if LEARNING_AVAILABLE else 0,
            "test_pr": test_pr_result,
            "review_body": self._format_review(review_comments, files_reviewed)[:3000],
        }

    def _create_test_pr(self, repo: str, original_pr: int,
                        base_branch: str, testable_files: List[Dict]) -> Dict:
        """Generates tests and creates a follow-up PR."""
        try:
            generated_tests = []

            for tf in testable_files[:3]:
                try:
                    gen_result = test_generator.generate(tf["code"], tf["filename"])
                    if gen_result.get("ok") and gen_result.get("tests"):
                        generated_tests.append({
                            "source_file": tf["filename"],
                            "test_file": gen_result.get("test_filename", "test_" + tf["filename"]),
                            "test_code": gen_result["tests"],
                            "framework": gen_result.get("framework", "pytest"),
                        })
                        logger.info(f"generated tests for {tf['filename']}")
                except Exception as e:
                    logger.warning(f"test gen failed for {tf['filename']}: {e}")

            if not generated_tests:
                return {"ok": False, "reason": "no tests generated"}

            branch_name = f"novamind/tests-pr-{original_pr}-{int(datetime.now(timezone.utc).timestamp())}"
            branch_result = self.gh.create_branch(repo, branch_name, from_branch=base_branch)
            if not branch_result.get("ok"):
                return {"ok": False, "error": "branch creation failed"}

            committed = 0
            for gt in generated_tests:
                source_dir = "/".join(gt["source_file"].split("/")[:-1])
                test_path = (source_dir + "/" + gt["test_file"]) if source_dir else gt["test_file"]

                commit_result = self.gh.create_or_update_file(
                    repo=repo,
                    path=test_path,
                    content=gt["test_code"],
                    message=f"Add tests for {gt['source_file']}\n\nGenerated by NovaMind Pro",
                    branch=branch_name,
                )
                if commit_result.get("ok"):
                    committed += 1

            if committed == 0:
                return {"ok": False, "error": "no commits succeeded"}

            pr_body = self._format_test_pr_body(generated_tests, original_pr)
            pr_result = self.gh.create_pr(
                repo=repo,
                title=f"🤖 NovaMind: Tests for PR #{original_pr}",
                body=pr_body,
                head=branch_name,
                base=base_branch,
            )

            return {
                "ok": True,
                "branch": branch_name,
                "committed": committed,
                "pr_url": pr_result.get("data", {}).get("html_url", ""),
                "pr_number": pr_result.get("data", {}).get("number"),
            }

        except Exception as e:
            logger.exception(f"test PR creation failed: {e}")
            return {"ok": False, "error": str(e)[:200]}

    def _format_comment(self, filename: str, verdict: str,
                        issues: List[Dict]) -> str:
        emoji = {"ok": "✅", "issues": "⚠️", "broken": "❌"}.get(verdict, "•")
        lines = [f"### {emoji} `{filename}` — {verdict}"]

        errors = [i for i in issues if i.get("severity") == "error"]
        warnings = [i for i in issues if i.get("severity") == "warning"]
        infos = [i for i in issues if i.get("severity") == "info"]

        for group, label, prefix in [
            (errors, "🔴 Errors", "-"),
            (warnings, "🟡 Warnings", "-"),
            (infos, "🔵 Notes", "-"),
        ]:
            if group:
                lines.append(f"\n**{label}:**")
                for i in group[:5]:
                    line = i.get("line", "?")
                    desc = i.get("description", "")
                    lines.append(f"{prefix} Line {line}: {desc}")

        return "\n".join(lines)

    def _format_review(self, comments: List[str], files_reviewed: int) -> str:
        header = (
            "## 🤖 NovaMind Review\n\n"
            f"تمت مراجعة **{files_reviewed}** ملف بواسطة NovaMind Pro.\n\n"
            "---\n\n"
        )
        footer = (
            "\n\n---\n"
            "*مدعوم بـ NovaMind Pro — نظام مراجعة ذاتي التعلم متعدد اللغات*\n"
            "*يدعم: Python, TypeScript, JavaScript, JSON, YAML, Markdown*\n"
        )
        if not comments:
            return header + "✅ **لا توجد مشاكل** — الكود نظيف!\n" + footer
        return header + "\n\n".join(comments) + footer

    def _format_test_pr_body(self, tests: List[Dict], original_pr: int) -> str:
        lines = [
            "## 🤖 NovaMind — Auto-Generated Tests",
            "",
            f"تم توليد اختبارات تلقائياً لـ PR #{original_pr}.",
            "",
            "### الملفات المُختبرة:",
            "",
        ]
        for t in tests:
            lines.append(f"- `{t['source_file']}` → `{t['test_file']}` ({t['framework']})")

        lines.append("")
        lines.append("---")
        lines.append("*مدعوم بـ NovaMind Pro — نظام توليد اختبارات ذاتي*")
        return "\n".join(lines)


pr_reviewer = PRReviewer()
