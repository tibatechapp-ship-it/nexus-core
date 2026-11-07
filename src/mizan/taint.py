"""Cross-file taint analysis inside the project (س3) — pure ``ast``.

The competitive review (MIZAN_ROADMAP.md س3) named the gap: complex
injection/SSRF flows that span files escape single-file scanners. MIZAN now
answers with a bounded, honest intra-project analysis:

* **sources** — ``input()``, ``os.getenv()``, ``os.environ[...]`` and
  ``sys.argv[...]`` (the declared set; external web frameworks are *not*
  modeled — that is س6 territory, not magic).
* **sinks** — ``eval``/``exec``, ``os.system``/``os.popen``, the
  ``subprocess`` family, and any ``.execute(…)`` call (SQL).
* **propagation** — assignments, unpacking, attribute/subscript stores,
  *call arguments* and *return values* across files: every project function
  is simulated with sources active, and every call into a project function
  re-enters that function with the precise tainted-parameter set (memoized,
  so call cycles terminate and each (function, mask) is traced once).
* **bounds** — a global step budget and a chain-length cap make the scan
  terminate; truncation is reported, never hidden (``TaintReport.truncated``).

Declared limits: names are matched textually (aliasing a source function
hides it), nested closures are opaque, taint via mutated globals is not
modeled, and only the project's own files are analyzed.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .reachability import iter_py_files

__all__ = ["TaintFinding", "TaintReport", "scan_tree"]

#: Callables whose *return* is attacker-controlled input.
SOURCE_CALLS: frozenset[str] = frozenset({"input", "os.getenv"})
#: Subscripted bases whose *item* is attacker-controlled input.
SOURCE_SUBSCRIPTS: frozenset[str] = frozenset({"os.environ", "sys.argv"})
#: Sinks matched on the full dotted name.
SINK_DOTTED: frozenset[str] = frozenset({
    "eval", "exec", "os.system", "os.popen",
    "subprocess.call", "subprocess.run", "subprocess.Popen",
    "subprocess.check_call", "subprocess.check_output",
    "subprocess.getoutput", "subprocess.getstatusoutput",
})
#: Sinks matched on the final attribute (receiver-agnostic SQL).
SINK_ATTRS: frozenset[str] = frozenset({"execute", "executemany"})

#: Global step budget — the analysis is bounded, and hitting the budget is
#: reported as ``truncated`` rather than passed off as a complete scan.
MAX_STEPS = 20000
#: Chain (source→sink path) length cap; deeper flows are not reported.
MAX_CHAIN = 64


class _BudgetExhausted(Exception):
    """Internal unwind signal — never escapes :func:`scan_tree`."""


@dataclass(frozen=True)
class TaintFinding:
    """One attacker-controlled source reaching one dangerous sink."""

    file: str
    line: int
    sink: str
    chain: tuple[str, ...]  # human-readable path, source → sink

    @property
    def key(self) -> tuple[str, int, str, tuple[str, ...]]:
        return (self.file, self.line, self.sink, self.chain)


@dataclass
class TaintReport:
    """Aggregated result of one scan."""

    findings: list[TaintFinding] = field(default_factory=list)
    files_scanned: int = 0
    unparsed: int = 0
    functions: int = 0
    truncated: bool = False


@dataclass
class _FuncDef:
    """A project function the interpreter can enter."""

    name: str
    file: str
    params: tuple[str, ...]
    node: ast.FunctionDef | ast.AsyncFunctionDef


def _dotted(node: ast.AST) -> str:
    """Best-effort dotted name of a Name/Attribute chain."""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _is_source_call(node: ast.Call) -> bool:
    return _dotted(node.func) in SOURCE_CALLS


def _is_source_subscript(node: ast.Subscript) -> bool:
    return _dotted(node.value) in SOURCE_SUBSCRIPTS


def _sink_name(node: ast.Call) -> str:
    """Return the sink label for a call, or ``""`` when not a sink."""
    dotted = _dotted(node.func)
    if dotted in SINK_DOTTED:
        return dotted
    if isinstance(node.func, ast.Attribute) and node.func.attr in SINK_ATTRS:
        return f"*.{node.func.attr}"
    return ""


class _Analyzer:
    """One scan pass over one tree (attack tracing with memoized re-entry)."""

    def __init__(self, funcs: dict[str, _FuncDef]) -> None:
        self.funcs = funcs
        self.findings: list[TaintFinding] = []
        self._seen_findings: set[tuple[str, int, str, tuple[str, ...]]] = set()
        # (func, tainted-param-mask) → (return-tainted, path-from-source).
        # Pre-seeded with the cycle placeholder so in-progress re-entry
        # terminates; the completed value overwrites it.
        self._visited: dict[tuple[str, frozenset[int]], tuple[bool, tuple[str, ...]]] = {}
        self._in_progress: set[tuple[str, frozenset[int]]] = set()
        self._steps = 0

    # -- budget ----------------------------------------------------------
    def _tick(self) -> None:
        self._steps += 1
        if self._steps > MAX_STEPS:
            raise _BudgetExhausted

    # -- tracing ----------------------------------------------------------
    def trace_attacks(self) -> None:
        """Simulate every function with sources active; record findings."""
        for fd in self.funcs.values():
            _Sim(self, fd, frozenset(), (), True).run()

    def enter_callee(
        self,
        callee: _FuncDef,
        tainted_params: frozenset[int],
        chain: tuple[str, ...],
    ) -> tuple[bool, tuple[str, ...]]:
        """Trace into ``callee`` → (return-tainted?, path-from-source).

        The path is the callee-internal chain (source step + intermediate
        call entries), so the caller stitches one source→sink path across
        files.
        """
        if len(chain) >= MAX_CHAIN:  # path cap: deeper flows are not reported
            return False, ()
        key = (callee.name, tainted_params)
        if key in self._visited:
            ret, path = self._visited[key]
            if ret:
                return ret, path
            # In-progress re-entry (a call cycle): our own taint flowed in
            # through the arguments, so the recursion conservatively counts
            # as tainted — declared upward bias, never toward silence.
            if key in self._in_progress:
                return True, ()
            return ret, path
        self._visited[key] = (False, ())  # cycle guard until traced
        self._in_progress.add(key)
        sim = _Sim(self, callee, tainted_params, chain, True)
        sim.run()
        self._in_progress.discard(key)
        result = (sim.ret_tainted, sim.ret_path)
        self._visited[key] = result
        return result

    def add_finding(self, finding: TaintFinding) -> None:
        if finding.key not in self._seen_findings:
            self._seen_findings.add(finding.key)
            self.findings.append(finding)


class _Sim:
    """Symbolic interpreter of one function body under one taint trace."""

    def __init__(
        self,
        analyzer: _Analyzer,
        fd: _FuncDef,
        tainted_params: frozenset[int],
        chain: tuple[str, ...],
        sources_active: bool,
    ) -> None:
        self.analyzer = analyzer
        self.fd = fd
        self.chain = chain
        self.sources_active = sources_active
        # The tainted-param mask refers to *argument positions*; for methods
        # (first param self/cls) arguments shift by one against the params.
        shift = 1 if (fd.params and fd.params[0] in ("self", "cls")) else 0
        self.env: dict[str, bool] = {
            p: (i - shift) in tainted_params
            for i, p in enumerate(fd.params)
        }
        self.ret_tainted = False
        #: path of steps inside this frame that carried taint to the most
        #: recent tainted value (source step first, call entries after).
        self.taint_path: tuple[str, ...] = ()
        #: the path that carried taint to the most recent tainted return.
        self.ret_path: tuple[str, ...] = ()

    # -- statements --------------------------------------------------------
    def run(self) -> None:
        self._exec_block(self.fd.node.body)

    def _exec_block(self, stmts: list[ast.stmt]) -> None:
        for st in stmts:
            self._exec_stmt(st)

    def _exec_stmt(self, st: ast.stmt) -> None:
        self.analyzer._tick()
        if isinstance(st, ast.Assign):
            taint = self._expr(st.value)
            for tgt in st.targets:
                self._bind(tgt, taint)
        elif isinstance(st, (ast.AugAssign, ast.AnnAssign)):
            taint = self._expr(st.value) if st.value else False
            if isinstance(st, ast.AugAssign):
                taint = taint or self._load(st.target)
            self._bind(st.target, taint)
        elif isinstance(st, ast.Return):
            if st.value is not None and self._expr(st.value):
                self.ret_tainted = True
                self.ret_path = self.taint_path
        elif isinstance(st, ast.Expr):
            self._expr(st.value)
        elif isinstance(st, ast.If):
            self._expr(st.test)
            # path join: a var is tainted if tainted on EITHER branch —
            # sequential execution would let the else-branch clobber the
            # if-branch's taint (a false negative, not conservatism)
            self._exec_join(st.body, st.orelse)
        elif isinstance(st, (ast.While, ast.For)):
            if isinstance(st, ast.For):
                self._bind(st.target, self._expr(st.iter))
            else:
                self._expr(st.test)
            self._exec_block(st.body)
            self._exec_block(st.orelse)
        elif isinstance(st, ast.Try):
            saved = dict(self.env)
            self._exec_block(st.body)
            env_try = dict(self.env)
            self.env.clear()
            self.env.update(saved)
            for handler in st.handlers:
                self._exec_block(handler.body)
            self._exec_block(st.orelse)
            for k, v in env_try.items():
                self.env[k] = self.env.get(k, False) or v
            self._exec_block(st.finalbody)
        elif isinstance(st, ast.With):
            for item in st.items:
                taint = self._expr(item.context_expr)
                if item.optional_vars is not None:
                    self._bind(item.optional_vars, taint)
            self._exec_block(st.body)
        elif isinstance(st, ast.Delete):
            for tgt in st.targets:
                if isinstance(tgt, ast.Name):
                    self.env.pop(tgt.id, None)
        # FunctionDef/ClassDef nested bodies are opaque (declared limit);
        # Raise/Assert/Pass/Import/Global/… carry no taint of their own.

    def _exec_join(self, *branches: list[ast.stmt]) -> None:
        """Run branches on isolated env copies and union the taint results."""
        base = dict(self.env)
        joined: dict[str, bool] = {}
        for branch in branches:
            self.env.clear()
            self.env.update(base)
            self._exec_block(branch)
            for k, v in self.env.items():
                joined[k] = joined.get(k, False) or v
        self.env.clear()
        self.env.update(joined)

    def _bind(self, target: ast.AST, taint: bool) -> None:
        if isinstance(target, ast.Name):
            self.env[target.id] = taint
        elif isinstance(target, ast.Attribute):
            self.env[_dotted(target)] = taint
        elif isinstance(target, ast.Subscript):
            # container[key] = taint ⇒ the whole container is suspect
            self._bind(target.value, taint or self._load(target.value))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._bind(elt, taint)

    def _load(self, target: ast.AST) -> bool:
        if isinstance(target, ast.Name):
            return self.env.get(target.id, False)
        if isinstance(target, ast.Attribute):
            dotted = _dotted(target)
            if dotted in self.env:
                return self.env[dotted]
            return self.env.get(dotted.split(".")[0], False)
        if isinstance(target, ast.Subscript):
            return self._load(target.value) or self._expr(target.slice)
        return False

    # -- expressions --------------------------------------------------------
    def _expr(self, node: ast.AST | None) -> bool:
        """Conservative: taint survives any operation it flows through."""
        if node is None:
            return False
        self.analyzer._tick()
        if isinstance(node, ast.Constant):
            return False
        if isinstance(node, ast.Name):
            return self.env.get(node.id, False)
        if isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted in self.env:
                return self.env[dotted]
            return self.env.get(dotted.split(".")[0], False)
        if isinstance(node, ast.Subscript):
            if self.sources_active and _is_source_subscript(node):
                self._note_source(_dotted(node.value), node.lineno)
                return True
            return self._load(node)
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, ast.NamedExpr):
            # walrus: bind the target so later reads see the taint
            taint = self._expr(node.value)
            self._bind(node.target, taint)
            return taint
        if isinstance(node, ast.Starred):
            return self._expr(node.value)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return any(self._expr(e) for e in node.elts)
        if isinstance(node, ast.Dict):
            return any(self._expr(k) or self._expr(v)
                       for k, v in zip(node.keys, node.values))
        if isinstance(node, ast.IfExp):
            return (self._expr(node.test) or self._expr(node.body)
                    or self._expr(node.orelse))
        if isinstance(node, ast.JoinedStr):
            return any(self._expr(v) for v in node.values)
        if isinstance(node, ast.FormattedValue):
            return self._expr(node.value)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return self._comprehension(node.generators, node.elt)
        if isinstance(node, ast.DictComp):
            return (self._comprehension(node.generators, node.key)
                    or self._comprehension(node.generators, node.value))
        if isinstance(node, ast.Lambda):
            return False  # closures are opaque (declared limit)
        if isinstance(node, ast.Compare):
            return self._expr(node.left)
        if isinstance(node, ast.Await):
            return self._expr(node.value)
        # UnaryOp / BinOp / BoolOp / NamedExpr / … → recurse generically
        return any(self._expr(child) for child in ast.iter_child_nodes(node))

    def _note_source(self, label: str, line: int) -> None:
        """Append the source location to this frame's taint path."""
        self.taint_path = self.taint_path + (f"{self.fd.file}:{line} {label}()",)

    def _comprehension(
        self, generators: list[ast.comprehension], elt: ast.AST,
    ) -> bool:
        tainted = False
        shadow: dict[str, bool] = {}
        for gen in generators:
            t = self._expr(gen.iter)
            if isinstance(gen.target, ast.Name):
                shadow[gen.target.id] = t
                tainted = tainted or t
        saved = dict(self.env)
        self.env.update(shadow)
        result = tainted or self._expr(elt)
        self.env.clear()
        self.env.update(saved)
        return result

    def _call(self, node: ast.Call) -> bool:
        self.analyzer._tick()
        if self.sources_active and _is_source_call(node):
            self._note_source(_dotted(node.func), node.lineno)
            return True
        # method receivers carry taint into the result (x.strip() of a
        # tainted x is tainted) — evaluated first so nested sources/sinks
        # inside the receiver chain are still visited
        receiver_taint = (
            self._expr(node.func.value)
            if isinstance(node.func, ast.Attribute) else False
        )
        sink = _sink_name(node)
        if sink and self.sources_active and self._args_tainted(node):
            self.analyzer.add_finding(TaintFinding(
                file=self.fd.file, line=node.lineno, sink=sink,
                chain=self.taint_path + self.chain,
            ))
        callee = self._resolve_callee(node)
        if callee is not None:
            tainted = self._tainted_params(callee, node)
            # enter the project function with the precise mask (the memo
            # keeps each (function, mask) simulated exactly once, and the
            # empty mask still enters once so internal sources are seen)
            step = f"{self.fd.file}:{node.lineno} → {callee.name}()"
            ret, inner = self.analyzer.enter_callee(
                callee, tainted, self.chain + (step,),
            )
            if ret:
                self.taint_path = self.taint_path + (step,) + inner
                return True
            return receiver_taint
        return receiver_taint or self._args_tainted(node)

    def _args_tainted(self, node: ast.Call) -> bool:
        return any(self._expr(a) for a in node.args) or any(
            self._expr(kw.value) for kw in node.keywords
        )

    def _resolve_callee(self, node: ast.Call) -> _FuncDef | None:
        dotted = _dotted(node.func)
        if not dotted:
            return None
        return self.analyzer.funcs.get(dotted.split(".")[-1])

    def _tainted_params(
        self, callee: _FuncDef, node: ast.Call,
    ) -> frozenset[int]:
        """Map call-site arg taint onto the callee's parameter indices."""
        params = list(callee.params)
        args = list(node.args)
        if (len(args) == len(params) - 1
                and params and params[0] in ("self", "cls")):
            params = params[1:]  # method call: receiver is not an argument
        tainted: set[int] = set()
        for i, arg in enumerate(args):
            if i >= len(params):
                break
            if isinstance(arg, ast.Starred):
                break  # *args unpacking: mapping is unknown — conservative
            if self._expr(arg):
                tainted.add(i)
        kw_names = {p: i for i, p in enumerate(params)}
        for kw in node.keywords:
            if kw.arg is None:
                break  # **kwargs: conservative stop
            idx = kw_names.get(kw.arg)
            if idx is not None and self._expr(kw.value):
                tainted.add(idx)
        return frozenset(tainted)


def _collect_functions(tree: ast.Module, rel: str) -> list[_FuncDef]:
    """Top-level and class-level functions (nested closures are opaque)."""
    out: list[_FuncDef] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(_FuncDef(
                name=node.name, file=rel,
                params=tuple(a.arg for a in node.args.args),
                node=node,
            ))
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(_FuncDef(
                        name=child.name, file=rel,
                        params=tuple(a.arg for a in child.args.args),
                        node=child,
                    ))
    return out


def scan_tree(root: Path) -> TaintReport:
    """Scan every project ``*.py`` file under ``root`` for source→sink flows.

    Same-name functions across files collapse to one definition (the last
    parsed wins) — a declared limit of name-based interprocedural
    resolution. Truncation (step budget) is surfaced, never hidden.
    """
    report = TaintReport()
    funcs: dict[str, _FuncDef] = {}
    for path in iter_py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        except (SyntaxError, ValueError, OSError, UnicodeDecodeError):
            report.unparsed += 1
            continue
        report.files_scanned += 1
        rel = str(path.relative_to(root))
        for fd in _collect_functions(tree, rel):
            funcs[fd.name] = fd
    report.functions = len(funcs)
    analyzer = _Analyzer(funcs)
    try:
        analyzer.trace_attacks()
    except _BudgetExhausted:
        report.truncated = True
    report.findings = analyzer.findings
    return report
