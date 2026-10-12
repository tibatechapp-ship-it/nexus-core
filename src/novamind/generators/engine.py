"""Template Engine — Jinja2 wrapper مع filters إضافية."""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Optional, Callable, List
from jinja2 import (
    Environment, FileSystemLoader, select_autoescape,
    TemplateNotFound, StrictUndefined,
)


def _to_snake(name: str) -> str:
    import re
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _to_kebab(name: str) -> str:
    return _to_snake(name).replace("_", "-")


def _to_pascal(name: str) -> str:
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_"))


def _to_camel(name: str) -> str:
    p = _to_pascal(name)
    return p[0].lower() + p[1:] if p else ""


class TemplateEngine:
    def __init__(
        self,
        templates_dir: Path,
        llm_fallback: Optional[Callable] = None,
        strict: bool = True,
    ):
        self.templates_dir = Path(templates_dir)
        self.llm_fallback = llm_fallback
        self.strict = strict

        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape([]),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            undefined=StrictUndefined if strict else None,
        )

        # filters إضافية
        self.env.filters["snake"] = _to_snake
        self.env.filters["kebab"] = _to_kebab
        self.env.filters["pascal"] = _to_pascal
        self.env.filters["camel"] = _to_camel

    def render(self, template_name: str, context: Dict) -> str:
        try:
            tmpl = self.env.get_template(template_name)
            return tmpl.render(**context)
        except TemplateNotFound:
            if self.llm_fallback:
                return self.llm_fallback(template_name, context)
            raise

    def render_string(self, source: str, context: Dict) -> str:
        """يرندر نص Jinja2 مباشر (بدون ملف)."""
        tmpl = self.env.from_string(source)
        return tmpl.render(**context)

    def has(self, template_name: str) -> bool:
        return (self.templates_dir / template_name).exists()

    def list_templates(self, subdir: str = "") -> List[str]:
        base = self.templates_dir / subdir if subdir else self.templates_dir
        return sorted(str(p.relative_to(self.templates_dir)) for p in base.rglob("*.j2"))
