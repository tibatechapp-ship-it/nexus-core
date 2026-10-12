"""
Worker - Full pipeline: analyze -> test -> fix -> learn
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import MAX_FIX_ATTEMPTS
from hooks.manager import hooks
from tools import registry
from novamind.core.git_manager import git_manager
from novamind.agents.tester import tester

logger = logging.getLogger("worker")


class Worker:
    def __init__(self, worker_id=0):
        self.worker_id = worker_id
        self.name = "worker-" + str(worker_id)

    async def process(self, task):
        start = datetime.now(timezone.utc)
        logger.info("[" + self.name + "] start: " + task.path)
        await hooks.trigger("session:start", {"worker": self.name, "path": task.path})

        result = {
            "worker": self.name, "path": task.path, "kind": task.kind,
            "started_at": start.isoformat(), "status": "unknown", "attempts": 0,
            "syntax_ok": False, "analysis": {}, "test": {}, "fixes": [], "lessons": [],
        }

        current_code = task.content

        try:
            syntax = tester.check(current_code)
            result["syntax_ok"] = syntax.get("ok", False)
            if not syntax.get("ok"):
                logger.warning("[" + self.name + "] syntax: " + str(syntax.get("error", ""))[:80])

            exec_result = tester.run(current_code)
            result["test"] = exec_result
            logger.info("[" + self.name + "] initial success=" + str(exec_result.get("success")))

            if exec_result.get("success"):
                logger.info("[" + self.name + "] passed on first try")
                result["status"] = "passed"
                await hooks.trigger("fix:success", {"lesson": "clean code: " + Path(task.path).name, "worker": self.name})
            else:
                logger.info("[" + self.name + "] analyzing...")
                analysis = {"verdict": "issues", "issues": []}
                try:
                    from novamind.agents.analyzer import analyzer
                    analysis = analyzer.analyze(current_code, task.path)
                    result["analysis"] = {"verdict": analysis.get("verdict"),
                                          "issues_count": len(analysis.get("issues", [])),
                                          "provider": analysis.get("provider", "")}
                    logger.info("[" + self.name + "] verdict: " + analysis.get("verdict", "?"))
                except Exception as e:
                    logger.warning("[" + self.name + "] analyzer failed: " + str(e))
                    result["analysis"] = {"error": str(e)[:200]}

                final_status = "failed"
                last_error = exec_result.get("stderr", "")

                try:
                    from novamind.agents.multi_fixer import multi_fixer
                    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
                        result["attempts"] = attempt
                        logger.info("[" + self.name + "] fix attempt " + str(attempt))
                        await hooks.trigger("fix:before", {"attempt": attempt, "worker": self.name})

                        fix_result = multi_fixer.fix(current_code, error=last_error,
                                                issues=analysis.get("issues", []),
                                                previous_attempts=[f["code"] for f in result["fixes"]])

                        if not fix_result.get("ok"):
                            logger.warning("[" + self.name + "] fixer failed: " + fix_result.get("error", ""))
                            break

                        fixed_code = fix_result["code"]
                        result["fixes"].append({"attempt": attempt, "provider": fix_result.get("provider", ""),
                                                 "model": fix_result.get("model", ""), "elapsed": fix_result.get("elapsed", 0.0),
                                                 "code": fixed_code[:2000]})

                        test_after = tester.run(fixed_code)
                        if test_after.get("success"):
                            logger.info("[" + self.name + "] fix " + str(attempt) + " succeeded")
                            current_code = fixed_code
                            result["test"] = test_after
                            final_status = "fixed"
                            await hooks.trigger("fix:success", {"lesson": "fixed: " + Path(task.path).name + " after " + str(attempt) + " attempts", "worker": self.name})
                            break
                        else:
                            logger.info("[" + self.name + "] fix " + str(attempt) + " still failing")
                            last_error = test_after.get("stderr", "")
                            current_code = fixed_code
                            analysis = {"verdict": "broken", "issues": []}
                except Exception as e:
                    logger.warning("[" + self.name + "] fixer error: " + str(e))
                    result["analysis"]["fixer_error"] = str(e)[:200]

                result["status"] = final_status
                if final_status == "failed":
                    await hooks.trigger("fix:failed", {"error": last_error[:200], "worker": self.name})

            try:
                from novamind.agents.learner import learner
                summary = ("Path: " + task.path + "\n"
                           "Status: " + result["status"] + "\n"
                           "Attempts: " + str(result["attempts"]) + "\n"
                           "Error: " + (result["test"].get("stderr", "")[:300] if not result["test"].get("success") else "none"))
                lesson = learner.learn(summary, source=task.path)
                if lesson:
                    result["lessons"].append(lesson)
            except Exception as e:
                logger.warning("[" + self.name + "] learner failed: " + str(e))

        except Exception as e:
            logger.exception("[" + self.name + "] error: " + str(e))
            result["status"] = "error"
            result["error"] = str(e)[:300]
            await hooks.trigger("tool:error", {"toolName": "worker", "error": str(e)[:200], "worker": self.name})

        finally:
            # Auto-commit git changes
            try:
                if git_manager.is_dirty():
                    git_manager.commit_smart(
                        task.path, result.get("status", "unknown"),
                        result.get("attempts", 0)
                    )
            except Exception as _ge:
                logger.warning("git commit failed: " + str(_ge))

            end = datetime.now(timezone.utc)
            result["ended_at"] = end.isoformat()
            result["duration_sec"] = round((end - start).total_seconds(), 2)
            try:
                out = Path(task.path).parent / (Path(task.path).stem + ".result.json")
                out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info("[" + self.name + "] saved: " + out.name)
            except Exception as e:
                logger.warning("failed to save result: " + str(e))
            await hooks.trigger("session:end", {"worker": self.name})
            logger.info("[" + self.name + "] done: " + result["status"] + " (" + str(result["duration_sec"]) + "s)")

        return result


worker_default = Worker(0)
