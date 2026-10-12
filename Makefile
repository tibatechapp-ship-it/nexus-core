# ═══════════════════════════════════════════════════════════════
# NovaMind — Makefile
# ═══════════════════════════════════════════════════════════════

.PHONY: help install test clean check sync push release tag

help:
	@echo "NovaMind v3.4.0 — Available targets:"
	@echo ""
	@echo "  make install       — Install package (editable)"
	@echo "  make test          — Run all tests"
	@echo "  make test-unit     — Run unit tests only"
	@echo "  make clean         — Clean temporary files"
	@echo "  make check         — Quick health check"
	@echo "  make sync          — Sync with origin/main"
	@echo "  make push          — Commit + push current branch"
	@echo "  make release       — Create release tag"
	@echo "  make tag V=X.Y.Z   — Create custom tag"

install:
	pip install -e ".[dev,observability]"

test:
	PYTHONPATH=src python3 -m pytest tests/ -v

test-unit:
	PYTHONPATH=src python3 -m pytest tests/unit/ -v

clean:
	find . -type d -name "__pycache__" -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.bak" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

check:
	PYTHONPATH=src python3 -c "import novamind; print('✅ novamind OK')"
	PYTHONPATH=src python3 -c "from novamind.registry import stats; print(f'✅ {stats()[\"agents_total\"]} agents')"
	PYTHONPATH=src python3 -c "from novamind.agents.factory import factory; print('✅ factory OK')"

sync:
	git fetch origin
	git pull origin main

push:
	git add -A
	git commit -m "$(m)" || true
	git push origin $$(git branch --show-current)

release:
	@if [ -z "$(V)" ]; then echo "Usage: make release V=3.5.0"; exit 1; fi
	git tag -a "v$(V)" -m "Release v$(V)"
	git push origin "v$(V)"
	@echo "✅ Released v$(V)"

tag:
	@if [ -z "$(V)" ]; then echo "Usage: make tag V=3.5.0"; exit 1; fi
	git tag -a "v$(V)" -m "Version v$(V)"
