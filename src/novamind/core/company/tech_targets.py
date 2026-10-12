"""Technical Targets - مهام تقنية حقيقية لكل تخصص."""
import logging
import random
import time
from typing import Dict, List, Any

logger = logging.getLogger("TechTargets")

TECHNICAL_MISSIONS = {
    "coder": {
        "level_1": [
            {"id": "c1_1", "task": "Write a Python function `safe_divide(a, b)` that returns None if b == 0. Include type hints and docstring.", "verify": "returns None on zero"},
            {"id": "c1_2", "task": "Write a Python function `flatten(nested_list)` that flattens arbitrary-depth nested lists.", "verify": "handles nested depth"},
            {"id": "c1_3", "task": "Write a context manager class `Timer` that measures and prints elapsed time.", "verify": "uses __enter__/__exit__"},
            {"id": "c1_4", "task": "Write a decorator `retry(times=3)` that retries a function on exception.", "verify": "retries on failure"},
            {"id": "c1_5", "task": "Write a generator `fibonacci(n)` that yields first n fibonacci numbers.", "verify": "uses yield"},
        ],
        "level_2": [
            {"id": "c2_1", "task": "Implement an LRU Cache class with get/put, capacity, using OrderedDict.", "verify": "correct LRU"},
            {"id": "c2_2", "task": "Write an async function `fetch_all(urls, max_concurrent=5)` using aiohttp with semaphore.", "verify": "uses Semaphore"},
            {"id": "c2_3", "task": "Implement iterative binary search on sorted list returning index or -1.", "verify": "O(log n)"},
            {"id": "c2_4", "task": "Write a class `RateLimiter` with token bucket algorithm for async functions.", "verify": "token bucket"},
            {"id": "c2_5", "task": "Write `deep_merge(dict1, dict2)` that recursively merges nested dicts.", "verify": "recursive merge"},
        ],
        "level_3": [
            {"id": "c3_1", "task": "Refactor to use strategy pattern: a class with if/elif chain for 5+ payment types.", "verify": "strategy pattern"},
            {"id": "c3_2", "task": "Optimize O(n^2) to O(n log n): find all pairs with sum = target in a list.", "verify": "O(n log n)"},
            {"id": "c3_3", "task": "Write a thread-safe metaclass `Singleton`.", "verify": "uses metaclass"},
        ],
    },
    "tester": {
        "level_1": [
            {"id": "t1_1", "task": "Write pytest tests for `def add(a, b): return a + b` with normal/edge/error cases.", "verify": "pytest format"},
            {"id": "t1_2", "task": "Write parametrized pytest tests for `is_prime(n)` testing 0, 1, 2, primes, composites.", "verify": "parametrize"},
            {"id": "t1_3", "task": "Write tests for a `Stack` class with push/pop/peek including empty stack.", "verify": "edge cases"},
        ],
        "level_2": [
            {"id": "t2_1", "task": "Write property-based tests using hypothesis for `sort_list(lst)`.", "verify": "hypothesis"},
            {"id": "t2_2", "task": "Write tests with mocks for a function that calls an external API.", "verify": "uses mock"},
            {"id": "t2_3", "task": "Write integration tests for a CRUD class using in-memory SQLite.", "verify": "full flow"},
        ],
        "level_3": [
            {"id": "t3_1", "task": "Write a fuzzing test for a parser that should never crash on random input.", "verify": "fuzzing"},
        ],
    },
    "security": {
        "level_1": [
            {"id": "s1_1", "task": "Review: cursor.execute(f\"SELECT * FROM users WHERE name = '{name}'\"). List SQLi + fix.", "verify": "detects SQLi"},
            {"id": "s1_2", "task": "Review: api_key = 'sk-abc123...' hardcoded. List vulnerability + fix.", "verify": "detects secret"},
            {"id": "s1_3", "task": "Review: pickle.loads(user_input). List vulnerability + fix.", "verify": "unsafe deser"},
        ],
        "level_2": [
            {"id": "s2_1", "task": "Review JWT: token in localStorage, no expiry check. List all vulnerabilities.", "verify": "JWT flaws"},
            {"id": "s2_2", "task": "Review: state-changing endpoint with GET and no CSRF token.", "verify": "CSRF"},
            {"id": "s2_3", "task": "Review: random.random() for password reset tokens.", "verify": "weak randomness"},
        ],
        "level_3": [
            {"id": "s3_1", "task": "Analyze login for timing attacks. Identify and fix the leak.", "verify": "timing attack"},
        ],
    },
    "reviewer": {
        "level_1": [
            {"id": "r1_1", "task": "Review: def f(x): return x.split(',').map(lambda y: y.strip()). List issues.", "verify": "detects .map bug"},
            {"id": "r1_2", "task": "Review: variable names data/temp/x in a 100-line function.", "verify": "naming"},
        ],
        "level_2": [
            {"id": "r2_1", "task": "Analyze cyclomatic complexity of 8 nested if/else. Suggest refactoring.", "verify": "complexity"},
            {"id": "r2_2", "task": "Review God Class with 15 methods. Suggest split.", "verify": "suggests split"},
        ],
        "level_3": [
            {"id": "r3_1", "task": "Review module for coupling, cohesion, SOLID violations.", "verify": "architectural"},
        ],
    },
    "analyzer": {
        "level_1": [
            {"id": "a1_1", "task": "Extract requirements from: 'Users login, reset password, see dashboard.'", "verify": "5+ requirements"},
            {"id": "a1_2", "task": "List edge cases for 'password reset'.", "verify": "5+ edge cases"},
        ],
        "level_2": [
            {"id": "a2_1", "task": "Write user stories + acceptance for 'shopping cart checkout'.", "verify": "user story format"},
            {"id": "a2_2", "task": "Design ER diagram for blog: users, posts, comments, tags.", "verify": "relations"},
        ],
        "level_3": [
            {"id": "a3_1", "task": "Analyze 'real-time chat': WebSocket vs SSE vs polling trade-offs.", "verify": "trade-offs"},
        ],
    },
    "fixer": {
        "level_1": [
            {"id": "f1_1", "task": "Fix: def add(a, b): return a - b. Explain the bug.", "verify": "wrong operator"},
            {"id": "f1_2", "task": "Fix: for i in range(len(lst)): print(lst[i+1]). Explain off-by-one.", "verify": "off-by-one"},
        ],
        "level_2": [
            {"id": "f2_1", "task": "Fix race condition: two threads incrementing shared counter without lock.", "verify": "uses Lock"},
            {"id": "f2_2", "task": "Fix memory leak: opening files without closing. Use context manager.", "verify": "with statement"},
        ],
        "level_3": [
            {"id": "f3_1", "task": "Fix production incident: API 500 for 10% under load. Debug + fix.", "verify": "systematic"},
        ],
    },
    "optimizer": {
        "level_1": [
            {"id": "o1_1", "task": "Optimize: sum([i*i for i in range(n)]). Use generator.", "verify": "generator"},
            {"id": "o1_2", "task": "Optimize repeated list lookup: convert to set for O(1).", "verify": "uses set"},
        ],
        "level_2": [
            {"id": "o2_1", "task": "Optimize nested loop for duplicates: O(n^2) -> O(n).", "verify": "O(n)"},
            {"id": "o2_2", "task": "Optimize DB N+1 problem. Use eager loading.", "verify": "fixes N+1"},
        ],
        "level_3": [
            {"id": "o3_1", "task": "Optimize API latency 2s -> <200ms. Identify bottlenecks.", "verify": "comprehensive"},
        ],
    },
    "refactor": {
        "level_1": [
            {"id": "rf1_1", "task": "Refactor: extract repeated code (3+ occurrences) into helper.", "verify": "extracts"},
        ],
        "level_2": [
            {"id": "rf2_1", "task": "Refactor: replace 10 if/elif with dict dispatch.", "verify": "dispatch"},
            {"id": "rf2_2", "task": "Refactor: split 200-line function into 5 smaller.", "verify": "splits"},
        ],
        "level_3": [
            {"id": "rf3_1", "task": "Refactor monolith into loosely-coupled modules.", "verify": "decouples"},
        ],
    },
    "doc": {
        "level_1": [
            {"id": "d1_1", "task": "Write complete Google-style docstring for `def process(data, opts)`.", "verify": "Google style"},
            {"id": "d1_2", "task": "Write README for a Python CLI tool: install, usage, examples.", "verify": "all sections"},
        ],
        "level_2": [
            {"id": "d2_1", "task": "Write OpenAPI 3.0 spec for a REST API with 3 endpoints.", "verify": "OpenAPI"},
            {"id": "d2_2", "task": "Write ADR for choosing PostgreSQL over MongoDB.", "verify": "ADR format"},
        ],
        "level_3": [
            {"id": "d3_1", "task": "Write complete runbook for DB failover incident.", "verify": "runbook"},
        ],
    },
    "arabic": {
        "level_1": [
            {"id": "ar1_1", "task": "Translate to professional Arabic: 'The API returns JSON with rate limiting applied.'", "verify": "technical Arabic"},
            {"id": "ar1_2", "task": "Write Arabic docstring for an email validation function.", "verify": "technical Arabic"},
        ],
    },
}


class TechTargetSystem:
    def __init__(self):
        self.missions = TECHNICAL_MISSIONS

    def get_missions(self, specialty, level, count=5):
        pool = self.missions.get(specialty, {}).get(f"level_{level}", [])
        if not pool:
            for fb in [1, 2, 3]:
                pool = self.missions.get(specialty, {}).get(f"level_{fb}", [])
                if pool:
                    break
        random.seed(int(time.time()))
        return random.sample(pool, min(count, len(pool)))

    def get_daily_mission_set(self, specialty, current_rank, count=5):
        if current_rank <= 2:
            level = 1
        elif current_rank <= 5:
            level = 2
        else:
            level = 3
        return self.get_missions(specialty, level, count)

    def get_verify_criteria(self, mission):
        return mission.get("verify", "")

    def stats(self):
        total = 0
        by_spec = {}
        for spec, levels in self.missions.items():
            c = sum(len(m) for m in levels.values())
            by_spec[spec] = c
            total += c
        return {"total_missions": total, "by_specialty": by_spec}
