"""NovaMind Generators — مولّدات الأكواد والوكلاء."""
from __future__ import annotations

# ═══ ما هو موجود فعلاً ═══
try:
    from novamind.generators.engine import TemplateEngine
except ImportError:
    TemplateEngine = None

try:
    from novamind.generators.composer import Composer
except ImportError:
    Composer = None

try:
    from novamind.generators.verifier import Verifier
except ImportError:
    Verifier = None

try:
    from novamind.generators.contract import GeneratedPart, VerifyReport
except ImportError:
    GeneratedPart = None
    VerifyReport = None

# ═══ Alias (GeneratorEngine = TemplateEngine) ═══
GeneratorEngine = TemplateEngine


__all__ = [
    "TemplateEngine",
    "GeneratorEngine",  # alias
    "Composer",
    "Verifier",
    "GeneratedPart",
    "VerifyReport",
]
