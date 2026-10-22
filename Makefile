# ═══════════════════════════════════════════════════════════════
# nexus-core — Makefile
#
# The framework surface (src/{agents,core,patterns,memory,learning,
# security,tools,tui} + the zyvo scripts) is gated by ruff, mypy, the
# annotation checker and coverage. The opt-in novamind + workbench/web
# layers are excluded from those gates and verified by their own tests —
# the scope is identical across pyproject.toml, scripts/check_annotations.py
# and the coverage config. `make check` runs the whole gate.
# ═══════════════════════════════════════════════════════════════

PY ?= python3

.PHONY: help install check lint type annotations test cov adversarial clean sync push release tag

help:
	@echo "nexus-core — available targets:"
	@echo ""
	@echo "  make check         — ALL gates: ruff + mypy + annotations + tests/coverage"
	@echo "  make lint          — ruff check ."
	@echo "  make type          — mypy on the framework surface"
	@echo "  make annotations   — every function fully type-annotated"
	@echo "  make test          — full pytest suite (no coverage)"
	@echo "  make cov           — pytest with coverage (framework floor 95%)"
	@echo "  make adversarial   — adversarial red-team suite"
	@echo "  make install       — editable install with dev tooling"
	@echo "  make clean         — remove caches and build artefacts"
	@echo "  make sync          — fetch + fast-forward from origin"
	@echo "  make push          — commit (m=) + push current branch"
	@echo "  make release V=X.Y.Z — tag and push a release"

install:
	$(PY) -m pip install -e ".[dev,tui]"

# ── the single definition of "green" ────────────────────────────────────────
check: lint type annotations sync-version cov
	@echo ""
	@echo "✅ nexus-core: all gates green."

lint:
	ruff check .

type:
	mypy zyvo-telegram.py zyvo-voice.py src

annotations:
	$(PY) scripts/check_annotations.py

sync-version:
	$(PY) scripts/sync_version.py

test:
	$(PY) -m pytest tests/ -q --ignore=tests/novamind

cov:
	$(PY) -m pytest --cov --cov-fail-under=95 --ignore=tests/novamind -q

adversarial:
	$(PY) -m pytest tests/adversarial -q

clean:
	find . -type d -name "__pycache__" -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache 2>/dev/null || true

sync:
	git fetch origin
	git pull --ff-only origin $$(git branch --show-current)

push:
	git add -A
	git commit -m "$(m)" || true
	git push origin $$(git branch --show-current)

release:
	@if [ -z "$(V)" ]; then echo "Usage: make release V=X.Y.Z"; exit 1; fi
	git tag -a "v$(V)" -m "nexus-core v$(V)"
	git push origin "v$(V)"
	@echo "✅ released v$(V)"

tag:
	@if [ -z "$(V)" ]; then echo "Usage: make tag V=X.Y.Z"; exit 1; fi
	git tag -a "v$(V)" -m "nexus-core v$(V)"
