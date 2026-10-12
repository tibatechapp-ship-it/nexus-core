"""
RealEvaluator — يقيّم وكيلاً حقيقياً باختبارات حقيقية

- يستدعي الوكيل المدرب فعلياً
- يشغّل اختبارات حقيقية
- يعطي درجة موثوقة
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
import time
import logging

from .real_tests import (
    get_real_tests,
    TestResult,
    TestOutcome,
)

logger = logging.getLogger("real_evaluator")


@dataclass
class RealEvaluationReport:
    """تقرير تقييم حقيقي"""
    agent_id: str
    spec: str
    total_tests: int
    passed: int
    failed: int
    errored: int
    total_score: float
    avg_duration: float
    results: List[TestResult]
    verdict: str  # passed / needs_retraining / failed
    timestamp: float = 0.0
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class RealEvaluator:
    """
    مُقيِّم حقيقي — يشغّل اختبارات فعلية على الوكيل
    
    المتطلبات:
    - agent_fn: دالة تستدعي الوكيل الحقيقي وتُرجع الرد
    """
    
    def __init__(
        self,
        passing_threshold: float = 0.70,
        min_tests_passed_ratio: float = 0.70,
    ):
        self.passing_threshold = passing_threshold
        self.min_ratio = min_tests_passed_ratio
        self.history: List[RealEvaluationReport] = []
    
    def evaluate(self, agent_id: str, spec: str, agent_fn: Callable) -> RealEvaluationReport:
        """
        قيّم وكيلاً حقيقياً
        
        Args:
            agent_id: معرف الوكيل
            spec: نوعه
            agent_fn: دالة تستدعي الوكيل: agent_fn(prompt) -> response
        """
        logger.info(f"Real evaluating {agent_id} (spec={spec})...")
        
        tests = get_real_tests(spec)
        
        if not tests:
            logger.warning(f"  No real tests for spec={spec}, using fallback")
            return self._make_empty_report(agent_id, spec)
        
        results: List[TestResult] = []
        
        for test_fn in tests:
            try:
                result = test_fn(agent_fn)
                results.append(result)
                icon = "✅" if result.outcome == TestOutcome.PASSED else "❌"
                logger.info(f"  {icon} {result.name}: {result.outcome.value} ({result.score:.2f})")
            except Exception as e:
                logger.error(f"  Test {test_fn.__name__} crashed: {e}")
                results.append(TestResult(
                    name=test_fn.__name__,
                    outcome=TestOutcome.ERROR,
                    score=0.0,
                    duration=0.0,
                    details=str(e),
                ))
        
        # حساب الإحصائيات
        passed = sum(1 for r in results if r.outcome == TestOutcome.PASSED)
        failed = sum(1 for r in results if r.outcome == TestOutcome.FAILED)
        errored = sum(1 for r in results if r.outcome == TestOutcome.ERROR)
        total_score = sum(r.score for r in results) / len(results) if results else 0.0
        passed_ratio = passed / len(results) if results else 0.0
        avg_duration = sum(r.duration for r in results) / len(results) if results else 0.0
        
        # القرار
        if total_score >= self.passing_threshold and passed_ratio >= self.min_ratio:
            verdict = "passed"
        elif total_score >= 0.50:
            verdict = "needs_retraining"
        else:
            verdict = "failed"
        
        report = RealEvaluationReport(
            agent_id=agent_id,
            spec=spec,
            total_tests=len(results),
            passed=passed,
            failed=failed,
            errored=errored,
            total_score=round(total_score, 3),
            avg_duration=round(avg_duration, 3),
            results=results,
            verdict=verdict,
        )
        
        self.history.append(report)
        
        icon = "✅" if verdict == "passed" else "⚠️" if verdict == "needs_retraining" else "❌"
        logger.info(
            f"  {icon} {agent_id}: {verdict} "
            f"(score={total_score:.2f}, ratio={passed_ratio:.2f})"
        )
        
        return report
    
    def _make_empty_report(self, agent_id: str, spec: str) -> RealEvaluationReport:
        return RealEvaluationReport(
            agent_id=agent_id,
            spec=spec,
            total_tests=0,
            passed=0,
            failed=0,
            errored=0,
            total_score=0.0,
            avg_duration=0.0,
            results=[],
            verdict="failed",
        )
    
    def stats(self) -> Dict:
        if not self.history:
            return {
                "total_evaluated": 0,
                "passed": 0,
                "needs_retraining": 0,
                "failed": 0,
                "avg_score": 0.0,
            }
        
        passed = sum(1 for r in self.history if r.verdict == "passed")
        retrain = sum(1 for r in self.history if r.verdict == "needs_retraining")
        failed = sum(1 for r in self.history if r.verdict == "failed")
        avg_score = sum(r.total_score for r in self.history) / len(self.history)
        
        return {
            "total_evaluated": len(self.history),
            "passed": passed,
            "needs_retraining": retrain,
            "failed": failed,
            "avg_score": round(avg_score, 3),
        }
