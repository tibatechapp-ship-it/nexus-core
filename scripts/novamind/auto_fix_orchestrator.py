"""Auto-Fix Orchestrator — coordinates agents in response to CI events."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@dataclass
class FailureContext:
    """Context of a CI/workflow failure."""
    event_type: str  # "workflow_run", "push", "pr", "schedule"
    workflow_name: str = ""
    conclusion: str = ""  # "failure", "cancelled", "timed_out"
    head_branch: str = ""
    head_sha: str = ""
    run_id: str = ""
    run_url: str = ""
    failed_jobs: list[str] = field(default_factory=list)
    logs_url: str = ""

    @classmethod
    def from_env(cls) -> "FailureContext":
        """Build context from GitHub Actions environment."""
        return cls(
            event_type=os.environ.get("GITHUB_EVENT_NAME", ""),
            workflow_name=os.environ.get("GITHUB_WORKFLOW", ""),
            conclusion=os.environ.get("CI_CONCLUSION", ""),
            head_branch=os.environ.get("GITHUB_REF_NAME", ""),
            head_sha=os.environ.get("GITHUB_SHA", ""),
            run_id=os.environ.get("GITHUB_RUN_ID", ""),
            run_url=(
                f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/"
                f"{os.environ.get('GITHUB_RUN_ID', '')}"
            ),
        )


@dataclass
class OrchestratorResult:
    """Result of orchestrator run."""
    context: FailureContext
    diagnoses: list[dict] = field(default_factory=list)
    fixes_applied: list[dict] = field(default_factory=list)
    reports: list[dict] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    success: bool = False


class AutoFixOrchestrator:
    """Orchestrates agents to diagnose and fix CI failures."""

    # Mapping: failure type → agents to run (in order)
    AGENT_PIPELINES = {
        "test_failure": ["ci_doctor", "fixer", "test_generator"],
        "import_error": ["ci_doctor", "fixer"],
        "lint_failure": ["fixer", "code_review"],
        "security_scan": ["security_agent", "fixer"],
        "docs_failure": ["docs_guardian"],
        "unknown": ["ci_doctor"],
    }

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._factory = None

    @property
    def factory(self):
        if self._factory is None:
            from novamind.agents.factory import factory
            self._factory = factory
        return self._factory

    def detect_failure_type(self, ctx: FailureContext) -> str:
        """Classify the failure based on workflow name and logs."""
        name = ctx.workflow_name.lower()

        if "docs" in name or "quality" in name:
            return "docs_failure"
        if "security" in name or "scan" in name:
            return "security_scan"
        if "test" in name:
            return "test_failure"
        if "lint" in name or "ruff" in name or "mypy" in name:
            return "lint_failure"

        return "unknown"

    def run_agent(self, agent_name: str, ctx: FailureContext) -> dict:
        """Run a single agent with the failure context."""
        try:
            agent = self.factory.get(agent_name)
            if agent is None:
                return {
                    "agent": agent_name,
                    "status": "skipped",
                    "error": f"agent not available: {agent_name}",
                }

            # Build a task description
            task = self._build_task(agent_name, ctx)

            # Most agents have a main() or run() method
            for method_name in ("run", "main", "process", "execute", "analyze"):
                if hasattr(agent, method_name):
                    method = getattr(agent, method_name)
                    if callable(method):
                        result = method(task)
                        return {
                            "agent": agent_name,
                            "status": "success",
                            "result": str(result)[:1000],
                        }

            return {
                "agent": agent_name,
                "status": "no_method",
                "error": "no callable method found",
            }

        except Exception as e:
            return {
                "agent": agent_name,
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
            }

    def _build_task(self, agent_name: str, ctx: FailureContext) -> str:
        """Build task description for the agent."""
        return (
            f"CI Failure Diagnosis\n"
            f"Workflow: {ctx.workflow_name}\n"
            f"Branch: {ctx.head_branch}\n"
            f"SHA: {ctx.head_sha[:8]}\n"
            f"Run URL: {ctx.run_url}\n"
            f"Conclusion: {ctx.conclusion}\n"
            f"Your job as {agent_name}: diagnose the failure, "
            f"identify root cause, suggest or apply fix."
        )

    def run(self, ctx: FailureContext) -> OrchestratorResult:
        """Main entry point."""
        import time
        start = time.monotonic()

        result = OrchestratorResult(context=ctx)

        # 1. Classify failure
        failure_type = self.detect_failure_type(ctx)
        result.recommendations.append(f"Detected failure type: {failure_type}")

        # 2. Pick pipeline
        pipeline = self.AGENT_PIPELINES.get(failure_type, self.AGENT_PIPELINES["unknown"])
        result.recommendations.append(f"Pipeline: {' → '.join(pipeline)}")

        # 3. Run each agent
        for agent_name in pipeline:
            r = self.run_agent(agent_name, ctx)
            result.diagnoses.append(r)

        result.duration_seconds = time.monotonic() - start
        result.success = all(
            d.get("status") in ("success", "skipped")
            for d in result.diagnoses
        )

        return result

    def to_json(self, result: OrchestratorResult) -> str:
        return json.dumps({
            "context": {
                "event_type": result.context.event_type,
                "workflow_name": result.context.workflow_name,
                "conclusion": result.context.conclusion,
                "head_branch": result.context.head_branch,
                "head_sha": result.context.head_sha,
                "run_url": result.context.run_url,
            },
            "diagnoses": result.diagnoses,
            "fixes_applied": result.fixes_applied,
            "reports": result.reports,
            "recommendations": result.recommendations,
            "duration_seconds": result.duration_seconds,
            "success": result.success,
        }, indent=2, ensure_ascii=False)


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Auto-Fix Orchestrator")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default="orchestrator-report.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    ctx = FailureContext.from_env()
    if args.verbose:
        print(f"Context: {ctx}")

    orch = AutoFixOrchestrator(dry_run=args.dry_run)
    result = orch.run(ctx)

    output_path = Path(args.output)
    output_path.write_text(orch.to_json(result), encoding="utf-8")

    print(f"✅ Report: {output_path}")
    print(f"   Success: {result.success}")
    print(f"   Duration: {result.duration_seconds:.2f}s")
    print(f"   Agents run: {len(result.diagnoses)}")

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
