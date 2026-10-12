"""DataScientist — تحليل بيانات متقدم."""
from novamind.base import BaseAgent
import statistics
from collections import Counter
import logging

log = logging.getLogger("DataScientist")


class DataScientist(BaseAgent):
    NAME = "data"
    DESCRIPTION = "يحلل البيانات ويستخرج الأنماط"
    ROLE = "researcher"
    LEVEL = 3
    CAPABILITIES = [
        "analyze_data", "find_patterns",
        "statistical_analysis", "detect_outliers",
        "compute_statistics", "correlate",
        "trend_analysis", "visualize_data", "datascience",
    ]

    def _register_tools(self):
        self.tools = {
            "analyze": self._analyze,
            "outliers": self._detect_outliers,
            "trend": self._trend,
        }

    async def handle(self, task):
        action = task.get("action", "").lower()
        params = task.get("params", {})

        try:
            if "analyze" in action or "stats" in action:
                return self._analyze(params)

            if "outlier" in action:
                return self._detect_outliers(params)

            if "trend" in action or "pattern" in action:
                return self._trend(params)

            return {"ok": True, "result": f"DataScientist: {action}"}

        except Exception as e:
            log.exception("DataScientist failed")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _analyze(self, params):
        """تحليل إحصائي شامل."""
        data = params.get("data", [])
        if not data:
            return {"ok": False, "error": "no data"}

        nums = [x for x in data if isinstance(x, (int, float))]
        if not nums:
            return {"ok": False, "error": "no numeric data"}

        result = {
            "count": len(nums),
            "sum": sum(nums),
            "mean": statistics.mean(nums),
            "median": statistics.median(nums),
            "min": min(nums),
            "max": max(nums),
        }

        if len(nums) > 1:
            result["stdev"] = statistics.stdev(nums)
            result["variance"] = statistics.variance(nums)

        return {"ok": True, "result": result}

    def _detect_outliers(self, params):
        """يكشف القيم الشاذة."""
        data = params.get("data", [])
        threshold = params.get("threshold", 2.0)

        if not data:
            return {"ok": False, "error": "no data"}

        nums = [x for x in data if isinstance(x, (int, float))]
        if len(nums) < 2:
            return {"ok": True, "result": {"outliers": [], "count": 0}}

        mean = statistics.mean(nums)
        try:
            stdev = statistics.stdev(nums)
        except Exception:
            stdev = 0

        if stdev == 0:
            return {"ok": True, "result": {"outliers": [], "count": 0}}

        outliers = [
            x for x in nums
            if abs((x - mean) / stdev) > threshold
        ]

        return {
            "ok": True,
            "result": {
                "outliers": outliers,
                "count": len(outliers),
                "mean": mean,
                "stdev": stdev,
            },
        }

    def _trend(self, params):
        """يحلل الاتجاه."""
        data = params.get("data", [])
        if len(data) < 2:
            return {"ok": False, "error": "need at least 2 points"}

        nums = [x for x in data if isinstance(x, (int, float))]
        if len(nums) < 2:
            return {"ok": False, "error": "no numeric data"}

        first_half = nums[:len(nums)//2]
        second_half = nums[len(nums)//2:]

        avg_first = statistics.mean(first_half)
        avg_second = statistics.mean(second_half)

        if avg_second > avg_first * 1.1:
            trend = "increasing"
        elif avg_second < avg_first * 0.9:
            trend = "decreasing"
        else:
            trend = "stable"

        return {
            "ok": True,
            "result": {
                "trend": trend,
                "first_half_avg": avg_first,
                "second_half_avg": avg_second,
                "delta": avg_second - avg_first,
            },
        }

# Auto-instance for registry
data_scientist = DataScientist()
