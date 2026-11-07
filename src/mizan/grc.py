"""Static GRC dashboard over multiple MIZAN reports (س5).

The competitive review (MIZAN_ROADMAP.md س5) named the gap: no central
governance view (CISO portfolio, ISO 27001 / SOC 2 / PCI DSS reporting).
The honest stdlib answer:

* an aggregate of *static* JSON reports (schema ``mizan.grc/1``) from many
  repositories — no server, no daemon: one HTML file you can attach to an
  audit ticket or publish to GitHub Pages;
* control mappings shipped as a *reviewed data file* (``data/controls.json``)
  and labeled "proposed coverage" — never a claim of certification;
* numbers computed by :func:`aggregate` and *tested to match* the inputs
  (the س5 exit gate), with HTML escaping by construction.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "SCHEMA",
    "ControlRow",
    "GrcError",
    "Finding",
    "Portfolio",
    "RepoReport",
    "aggregate",
    "control_coverage",
    "controls_path",
    "load_controls",
    "load_report",
    "render_html",
]

#: The one report schema this aggregator accepts.
SCHEMA = "mizan.grc/1"

_SEV_ORDER = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0, "UNKNOWN": 1}
_SEV_CSS = {
    "CRITICAL": "#7f1d1d", "HIGH": "#b91c1c", "MEDIUM": "#b45309",
    "LOW": "#1d4ed8", "UNKNOWN": "#525252",
}
_OPEN_STATES = {"open", "unknown", ""}


class GrcError(ValueError):
    """A report or controls file does not conform to its declared schema."""


@dataclass(frozen=True)
class Finding:
    """One normalized finding from any repository report."""

    repo: str
    rule_id: str
    severity: str
    message: str
    path: str
    line: int
    state: str

    @property
    def is_open(self) -> bool:
        return self.state.lower() in _OPEN_STATES

    @property
    def sev_rank(self) -> int:
        return _SEV_ORDER.get(self.severity.upper(), 1)


@dataclass(frozen=True)
class RepoReport:
    """One parsed report file."""

    repo: str
    generated_at: str
    findings: tuple[Finding, ...]
    fixes_planned: int = 0
    fixes_applied: int = 0


def load_report(path: Path) -> RepoReport:
    """Load and validate one ``mizan.grc/1`` report."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GrcError(f"cannot read report {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GrcError(f"{path}: report must be a JSON object")
    schema = payload.get("schema", SCHEMA)
    if schema != SCHEMA:
        raise GrcError(f"{path}: unsupported schema {schema!r} (want {SCHEMA!r})")
    repo = str(payload.get("repo", "")).strip()
    if not repo:
        raise GrcError(f"{path}: missing 'repo'")
    rows = payload.get("findings")
    if not isinstance(rows, list):
        raise GrcError(f"{path}: missing 'findings' list")
    findings: list[Finding] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise GrcError(f"{path}: finding #{i} must be an object")
        findings.append(Finding(
            repo=repo,
            rule_id=str(row.get("rule_id", "?")),
            severity=str(row.get("severity", "UNKNOWN")).upper(),
            message=str(row.get("message", "")),
            path=str(row.get("path", "")),
            line=int(row.get("line", 0)),
            state=str(row.get("state", "open")).lower(),
        ))
    fixes = payload.get("fixes") or {}
    if not isinstance(fixes, dict):
        raise GrcError(f"{path}: 'fixes' must be an object")
    return RepoReport(
        repo=repo,
        generated_at=str(payload.get("generated_at", "")),
        findings=tuple(findings),
        fixes_planned=int(fixes.get("planned", 0)),
        fixes_applied=int(fixes.get("applied", 0)),
    )


@dataclass
class Portfolio:
    """The aggregated view the dashboard renders."""

    reports: list[RepoReport] = field(default_factory=list)
    latest: dict[str, RepoReport] = field(default_factory=dict)

    @property
    def open_findings(self) -> list[Finding]:
        """Open findings from the *latest* report of each repository."""
        out: list[Finding] = []
        for rep in self.latest.values():
            out.extend(f for f in rep.findings if f.is_open)
        return out

    def by_severity(self) -> dict[str, int]:
        totals = {sev: 0 for sev in _SEV_ORDER}
        for f in self.open_findings:
            totals[f.severity if f.severity in totals else "UNKNOWN"] += 1
        return totals

    def by_repo(self) -> dict[str, int]:
        return {
            repo: sum(1 for f in rep.findings if f.is_open)
            for repo, rep in sorted(self.latest.items())
        }

    def top_risks(self, n: int = 10) -> list[Finding]:
        return sorted(
            self.open_findings,
            key=lambda f: (-f.sev_rank, f.repo, f.path, f.line),
        )[:n]

    def trend(self) -> list[tuple[str, int]]:
        """Open-finding count per report date (portfolio-wide)."""
        per_date: dict[str, int] = {}
        for rep in self.reports:
            date = rep.generated_at[:10] if rep.generated_at else "?"
            per_date[date] = per_date.get(date, 0) + sum(
                1 for f in rep.findings if f.is_open
            )
        return sorted(per_date.items())

    def fixes(self) -> tuple[int, int]:
        """(planned, applied) summed over each repo's latest report."""
        return (
            sum(r.fixes_planned for r in self.latest.values()),
            sum(r.fixes_applied for r in self.latest.values()),
        )


def aggregate(reports: list[RepoReport]) -> Portfolio:
    """Fold reports into a portfolio; latest report per repo wins KPIs."""
    latest: dict[str, RepoReport] = {}
    for rep in sorted(reports, key=lambda r: r.generated_at):
        latest[rep.repo] = rep  # later timestamps overwrite earlier ones
    return Portfolio(reports=list(reports), latest=latest)


def controls_path() -> Path:
    """Built-in reviewed control-map file (``mizan.controls/1``)."""
    return Path(__file__).with_name("data") / "controls.json"


def load_controls(path: Path | None = None) -> dict[str, list[dict[str, str]]]:
    """Load the reviewed control mappings (framework → control rows)."""
    real = path or controls_path()
    try:
        payload = json.loads(real.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GrcError(f"cannot read controls {real}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GrcError(f"{real}: controls file must be a JSON object")
    frameworks = payload.get("frameworks")
    if not isinstance(frameworks, dict) or not frameworks:
        raise GrcError(f"{real}: missing 'frameworks' mapping")
    for name, rows in frameworks.items():
        if not isinstance(rows, list):
            raise GrcError(f"{real}: framework {name!r} must be a list")
        for row in rows:
            if not isinstance(row, dict) or "id" not in row or "title" not in row:
                raise GrcError(f"{real}: framework {name!r}: bad control row")
    return frameworks


@dataclass(frozen=True)
class ControlRow:
    """One control with its machine-checked evidence count."""

    framework: str
    control_id: str
    title: str
    rule_ids: tuple[str, ...]
    open_findings: int


def control_coverage(
    portfolio: Portfolio,
    frameworks: dict[str, list[dict[str, str]]],
) -> list[ControlRow]:
    """Map open findings onto controls (proposed coverage, declared)."""
    open_by_rule: dict[str, int] = {}
    for f in portfolio.open_findings:
        open_by_rule[f.rule_id] = open_by_rule.get(f.rule_id, 0) + 1
    rows: list[ControlRow] = []
    for fw, controls in frameworks.items():
        for ctrl in controls:
            rule_ids = tuple(str(r) for r in ctrl.get("rule_ids", []))
            rows.append(ControlRow(
                framework=fw,
                control_id=str(ctrl["id"]),
                title=str(ctrl["title"]),
                rule_ids=rule_ids,
                open_findings=sum(
                    open_by_rule.get(r, 0) for r in rule_ids
                ),
            ))
    return rows


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _bars(totals: dict[str, int], total: int) -> str:
    if total == 0:
        return "<p class=\"empty\">لا مكتشفات مفتوحة — صفر صادق، ليس صمتًا.</p>"
    parts = []
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"):
        n = totals.get(sev, 0)
        if n == 0:
            continue
        pct = round(100.0 * n / total, 1)
        parts.append(
            f'<div class="bar-row"><span class="sev">{sev}</span>'
            f'<span class="bar"><span class="fill" '
            f'style="width:{pct}%;background:{_SEV_CSS[sev]}"></span></span>'
            f'<span class="num">{n} ({pct}%)</span></div>'
        )
    return "\n".join(parts)


def render_html(
    portfolio: Portfolio,
    frameworks: dict[str, list[dict[str, str]]] | None = None,
) -> str:
    """Render the full static RTL dashboard (one file, zero JS)."""
    totals = portfolio.by_severity()
    total = sum(totals.values())
    repos = portfolio.by_repo()
    fixes_planned, fixes_applied = portfolio.fixes()
    controls = (
        control_coverage(portfolio, frameworks)
        if frameworks is not None else []
    )
    fw_names = sorted(frameworks) if frameworks is not None else []

    repo_rows = "\n".join(
        f"<tr><td>{_esc(r)}</td><td>{n}</td></tr>" for r, n in repos.items()
    ) or '<tr><td colspan="2" class="empty">لا تقارير</td></tr>'

    top_rows = "\n".join(
        f"<tr><td>{_esc(f.severity)}</td><td>{_esc(f.rule_id)}</td>"
        f"<td>{_esc(f.repo)}</td><td><code>{_esc(f.path)}:{f.line}</code></td>"
        f"<td>{_esc(f.message)}</td></tr>"
        for f in portfolio.top_risks()
    ) or '<tr><td colspan="5" class="empty">لا مخاطر مفتوحة</td></tr>'

    trend_rows = "\n".join(
        f"<tr><td>{_esc(date)}</td><td>{n}</td></tr>"
        for date, n in portfolio.trend()
    ) or '<tr><td colspan="2" class="empty">لا سلسلة زمنية بعد</td></tr>'

    control_blocks = []
    for fw in fw_names:
        rows = "\n".join(
            f"<tr><td><b>{_esc(c.control_id)}</b></td><td>{_esc(c.title)}</td>"
            f"<td><code>{_esc(', '.join(c.rule_ids))}</code></td>"
            f"<td>{c.open_findings}</td></tr>"
            for c in controls if c.framework == fw
        )
        control_blocks.append(
            f'<h3>خرائط الضوابط — {_esc(fw)} '
            '<span class="note">(تغطية مقترحة — لا ادعاء شهادة)</span></h3>'
            '<table><thead><tr><th>الضابط</th><th>العنوان</th>'
            '<th>القواعد المرتبطة</th><th>مكتشفات مفتوحة</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )
    controls_html = "\n".join(control_blocks) if control_blocks else \
        "<p class=\"empty\">خرائط الضوابط غير مفعّلة لهذه اللوحة.</p>"

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MIZAN GRC — لوحة الحوكمة</title>
<style>
  body {{ font-family: "Noto Sans Arabic", "Segoe UI", Tahoma, sans-serif;
         margin: 0; background: #f7f7f5; color: #171717; }}
  main {{ max-width: 980px; margin: 0 auto; padding: 24px 16px; }}
  h1 {{ font-size: 1.5rem; }} h2 {{ margin-top: 2rem; font-size: 1.15rem;
       border-bottom: 2px solid #d4d4d4; padding-bottom: .3rem; }}
  h3 {{ font-size: 1rem; margin-bottom: .4rem; }}
  .cards {{ display: flex; gap: 12px; flex-wrap: wrap; }}
  .card {{ background: #fff; border: 1px solid #e5e5e5; border-radius: 10px;
          padding: 14px 18px; min-width: 130px; }}
  .card .k {{ font-size: 1.7rem; font-weight: 700; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff;
          font-size: .92rem; }}
  th, td {{ border: 1px solid #e5e5e5; padding: 7px 10px; text-align: right; }}
  th {{ background: #efeeec; }}
  code {{ font-size: .85em; direction: ltr; unicode-bidi: embed; }}
  .bar-row {{ display: flex; align-items: center; gap: 8px; margin: 6px 0; }}
  .sev {{ width: 74px; font-weight: 600; font-size: .85rem; }}
  .bar {{ flex: 1; background: #e5e5e5; border-radius: 4px; height: 14px;
         overflow: hidden; }}
  .fill {{ display: block; height: 100%; }}
  .num {{ width: 96px; font-variant-numeric: tabular-nums; }}
  .empty {{ color: #737373; font-style: italic; }}
  .note {{ color: #737373; font-size: .8rem; font-weight: 400; }}
  footer {{ margin-top: 3rem; color: #737373; font-size: .82rem;
           border-top: 1px solid #e5e5e5; padding-top: 1rem; }}
</style>
</head>
<body><main>
<h1>ميزان GRC — لوحة الحوكمة الساكنة</h1>
<p class="note">مولّدة آلياً من تقارير <code>mizan.grc/1</code> — بلا خادم،
بلا JS، بلا اتصال. الأرقام محسوبة من التقارير المجمّعة.</p>

<h2>المؤشرات</h2>
<div class="cards">
  <div class="card"><div class="k">{total}</div>مكتشفات مفتوحة</div>
  <div class="card"><div class="k">{len(repos)}</div>مستودعات</div>
  <div class="card"><div class="k">{fixes_planned}</div>إصلاحات مُخططة</div>
  <div class="card"><div class="k">{fixes_applied}</div>إصلاحات مطبقة</div>
</div>

<h2>توزيع الخطورة</h2>
{_bars(totals, total)}

<h2>حسب المستودع</h2>
<table><thead><tr><th>المستودع</th><th>مفتوح</th></tr></thead>
<tbody>{repo_rows}</tbody></table>

<h2>أعلى 10 مخاطر</h2>
<table><thead><tr><th>الخطورة</th><th>القاعدة</th><th>المستودع</th>
<th>الموقع</th><th>الرسالة</th></tr></thead>
<tbody>{top_rows}</tbody></table>

<h2>الاتجاه الزمني</h2>
<table><thead><tr><th>التاريخ</th><th>مفتوح</th></tr></thead>
<tbody>{trend_rows}</tbody></table>

<h2>الضوابط</h2>
{controls_html}

<footer>MIZAN GRC (س5) — خرائط الضوابط «تغطية مقترحة» من ملف بيانات مُراجَع،
لا ادعاء امتثال مُحقَّق ولا شهادات. المصدر: ملفات تقارير ثابتة قابلة للتدقيق.</footer>
</main></body></html>
"""
