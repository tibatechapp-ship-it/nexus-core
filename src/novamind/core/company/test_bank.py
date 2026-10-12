"""Test Bank - اختبارات مختصرة لكل تخصص."""
import random
from typing import List, Dict, Any

TEST_BANK = {
    "coder": {
        "level_1": [
            {"id": "c1", "task": "Write Python function add(a,b) with type hints. Output only code."},
            {"id": "c2", "task": "Write Python function is_even(n) returning bool. Output only code."},
            {"id": "c3", "task": "Write Python function reverse(s). Output only code."},
        ],
        "level_2": [
            {"id": "c4", "task": "Write is_prime(n) with edge cases. Output only code."},
            {"id": "c5", "task": "Write remove_duplicates(lst) preserving order. Output only code."},
            {"id": "c6", "task": "Write fibonacci(n) with memoization. Output only code."},
        ],
        "level_3": [
            {"id": "c7", "task": "Implement Stack class with push/pop/peek. Output only code."},
            {"id": "c8", "task": "Write LRU Cache with OrderedDict. Output only code."},
        ],
    },
    "tester": {
        "level_1": [
            {"id": "t1", "task": "Write pytest tests for add(a,b). Output only code."},
            {"id": "t2", "task": "Write parametrized pytest for is_prime(n). Output only code."},
        ],
        "level_2": [
            {"id": "t3", "task": "Write property-based tests using hypothesis for sort_list. Output only code."},
            {"id": "t4", "task": "Write tests with mocks for external API calls. Output only code."},
        ],
    },
    "security": {
        "level_1": [
            {"id": "s1", "task": "Review SQL query with f-string for SQLi. List vulnerability + fix."},
            {"id": "s2", "task": "Review hardcoded api_key='sk-abc'. List vulnerability + fix."},
        ],
        "level_2": [
            {"id": "s3", "task": "Review JWT in localStorage without expiry check. List issues."},
            {"id": "s4", "task": "Review random.random() for password reset tokens. Fix."},
        ],
    },
    "fixer": {
        "level_1": [
            {"id": "f1", "task": "Fix: def add(a,b): return a-b. Explain and fix."},
            {"id": "f2", "task": "Fix: for i in range(len(lst)): print(lst[i+1]). Fix off-by-one."},
        ],
        "level_2": [
            {"id": "f3", "task": "Fix race condition in shared counter. Provide Lock-based solution."},
        ],
    },
    "reviewer": {
        "level_1": [
            {"id": "r1", "task": "Review: def f(x): return x.split(',').map(...). List issues."},
            {"id": "r2", "task": "Review: 100-line function with unclear names. Suggest improvements."},
        ],
    },
    "analyzer": {
        "level_1": [
            {"id": "a1", "task": "Extract requirements from: 'Users login, reset password, see dashboard.'"},
            {"id": "a2", "task": "List edge cases for password reset feature."},
        ],
    },
    "optimizer": {
        "level_1": [
            {"id": "o1", "task": "Optimize sum([i*i for i in range(n)]). Use generator."},
            {"id": "o2", "task": "Optimize repeated list lookup. Use set."},
        ],
    },
    "refactor": {
        "level_1": [
            {"id": "rf1", "task": "Refactor: extract repeated code into helper function."},
            {"id": "rf2", "task": "Refactor: replace magic numbers with constants."},
        ],
    },
    "doc": {
        "level_1": [
            {"id": "d1", "task": "Write Google-style docstring for def process(data, opts)."},
            {"id": "d2", "task": "Write README for a Python CLI tool."},
        ],
    },
    "arabic": {
        "level_1": [
            {"id": "ar1", "task": "Translate to Arabic: 'The API returns JSON with rate limiting.'"},
            {"id": "ar2", "task": "Write Arabic docstring for email validation function."},
        ],
    },
}

RANK_TO_LEVEL = {
    "RECRUIT": 1, "PRIVATE": 1,
    "CORPORAL": 2, "SERGEANT": 2,
    "LIEUTENANT": 3, "CAPTAIN": 3,
    "MAJOR": 4, "COLONEL": 4, "GENERAL": 4, "COMMANDANT": 4,
}


class TestBank:
    def __init__(self):
        self.bank = TEST_BANK
        self.rank_to_level = RANK_TO_LEVEL
    
    def get_tests(self, specialty: str, rank_name: str, count: int = 3) -> List[Dict]:
        level = self.rank_to_level.get(rank_name, 1)
        pool = self.bank.get(specialty, {}).get(f"level_{level}", [])
        if not pool:
            for lvl in [1, 2, 3]:
                pool = self.bank.get(specialty, {}).get(f"level_{lvl}", [])
                if pool:
                    break
        if not pool:
            return []
        return random.sample(pool, min(count, len(pool)))
    
    def stats(self) -> Dict:
        total = 0
        by_spec = {}
        for spec, levels in self.bank.items():
            count = sum(len(t) for t in levels.values())
            by_spec[spec] = count
            total += count
        return {"total": total, "by_specialty": by_spec}
