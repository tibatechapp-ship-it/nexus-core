"""Tests for novamind.registry.v2."""
from __future__ import annotations

import pytest


class TestRegistryV2Basics:

    def test_import(self):
        from novamind.registry.v2 import (
            UnifiedRegistry, Category, Criticality, REGISTRY,
        )
        assert REGISTRY is not None
        assert UnifiedRegistry is not None
        assert Category is not None
        assert Criticality is not None

    def test_stats(self):
        from novamind.registry.v2 import REGISTRY
        stats = REGISTRY.stats()
        assert stats['total'] == 79
        assert 'by_category' in stats
        assert 'by_criticality' in stats

    def test_categories(self):
        from novamind.registry.v2 import REGISTRY, Category
        stats = REGISTRY.stats()
        by_cat = stats['by_category']
        for cat in Category:
            assert cat.value in by_cat, f"Category {cat.value} missing"

    def test_core_agents_count(self):
        from novamind.registry.v2 import REGISTRY
        core = REGISTRY.list_core()
        assert len(core) == 21, f"Expected 21 core, got {len(core)}"

    def test_core_agents_contains_coder(self):
        from novamind.registry.v2 import REGISTRY
        core = REGISTRY.list_core()
        core_names = [c if isinstance(c, str) else c.name for c in core]
        assert 'coder' in core_names
        assert 'analyzer' in core_names
        assert 'security_agent' in core_names

    def test_list_by_category(self):
        from novamind.registry.v2 import REGISTRY, Category
        code_agents = REGISTRY.list_by_category(Category.CODE)
        assert len(code_agents) == 15

    def test_agent_spec_dataclass(self):
        from novamind.registry.v2 import AgentSpec
        assert hasattr(AgentSpec, '__dataclass_fields__')
