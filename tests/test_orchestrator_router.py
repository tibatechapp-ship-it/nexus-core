"""Router tests."""
from src.orchestrator.router import route, route_with_reason


class FakeGenome:
    def __init__(self, overrides):
        self.overrides = overrides
    def fitness_of(self, name):
        return self.overrides.get(name, 0.5)


def test_write_tests_routes_to_tester():
    assert route("write tests for X") == "tester"


def test_deploy_routes_to_devops():
    assert route("deploy to prod") == "devops"


def test_tie_broken_by_fitness():
    g = FakeGenome({"coder": 0.9})
    assert route("engineering help", genome=g) == "coder"


def test_route_with_reason_has_alternatives():
    info = route_with_reason("engineering")
    assert info["agent"] is not None
    assert isinstance(info["score"], float)
    assert isinstance(info["alternatives"], list)


def test_empty_returns_coder():
    assert route("") == "coder"
    assert route(None) == "coder"
