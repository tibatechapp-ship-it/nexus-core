"""اختبارات فروع إضافية — مسارات الفشل الصريح والبديل المعلن.

كل اختبار هنا يمشي مسارًا معلنًا في العقد لكنه نادر الحدوث: فشل
مزوّد، رد بلا تغييرات، غياب أداة تشغيل، بدائل المزوّد الحقيقي.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from src.org.agents import AgentRuntime, AgentSpec, Tool, ToolRegistry
from src.org.contracts import Mission, TaskResult, TaskSpec
from src.org.departments import MissionContext, RepoIntelDept
from src.org.providers import (
    ModelResponse,
    MockProvider,
    OpenAICompatProvider,
    ProviderConfig,
    ProviderError,
    ProviderPool,
    Usage,
)
from src.org.store import OrgStore
from src.ops.store import OpsStore

OBJECTIVE = ("أضف حارس قسمة على صفر إلى دالة divide في وحدة calc.mathops "
             "مع اختبارات للحدية")


class _Handler(BaseHTTPRequestHandler):
    """خادم محلي صغير لمسار النجاح الحقيقي للمُكيّف المتوافق."""

    def do_POST(self) -> None:  # noqa: N802 — واجهة المكتبة القياسية
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = b'{"choices":[{"message":{"content":"{\\"ok\\": 1}",' \
               b'"finish_reason":"stop"}}],"usage":{"prompt_tokens":5,' \
               b'"completion_tokens":3}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # pragma: no cover
        pass


class TestOpenAICompatRealPath:
    def test_success_via_local_http(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatProvider(ProviderConfig(
                name="openai-compat", model="test-model",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="k", timeout_s=5))
            resp = provider.complete([{"role": "user", "content": "hi"}])
            assert resp.text == '{"ok": 1}'
            assert resp.usage.in_tokens == 5
            assert resp.finish_reason == "stop"
        finally:
            server.shutdown()

    def test_pool_falls_back_to_mock(self) -> None:
        """مزوّد حقيقي ميت ثم بديل محلي — السلسلة تعمل بلا شبكة خارجية."""
        pool = ProviderPool([
            ProviderConfig(name="openai-compat", model="m",
                           base_url="http://127.0.0.1:9/v1", timeout_s=1),
            ProviderConfig(name="mock", model="mock-1"),
        ])
        resp = pool.complete_with_fallback(
            [{"role": "user", "content": "أجب JSON"}])
        assert resp.provider == "mock"
        assert pool.last_errors  # محاولة الحقيقي مسجلة


class TestAgentEdgePaths:
    def test_complete_returns_raw_response(self) -> None:
        store = OrgStore(":memory:")
        runtime = AgentRuntime(ProviderPool([ProviderConfig(name="mock", model="mock-1")]),
                               ToolRegistry(), store, allow_simulated=True)
        spec = AgentSpec(role="qa:runner", dept="qa", mission_id="m")
        resp = runtime.complete(spec, "أجب")
        assert isinstance(resp, ModelResponse)
        assert resp.simulated is True

    def test_complete_exhausted_raises(self) -> None:
        class BoomPool(ProviderPool):
            def complete_with_fallback(self, messages, **kwargs):  # type: ignore[override]
                raise ProviderError("ميت")

        runtime = AgentRuntime(BoomPool(), ToolRegistry(), OrgStore(":memory:"))
        spec = AgentSpec(role="qa:runner", dept="qa", mission_id="m",
                         max_retries=0)
        with pytest.raises(ProviderError, match="استنفد"):
            runtime.complete(spec, "أجب")

    def test_invalid_tool_registration(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(ValueError):
            registry.register(Tool("", "بلا اسم", lambda: {}))
        with pytest.raises(ValueError):
            registry.register(Tool("x", "بلا دالة", "not-callable"))  # type: ignore[arg-type]

    def test_record_failure_never_raises(self) -> None:
        """سجل الوكيل الفاشل لا يُسقط الاستدعاء (حد النظافة المعلن)."""
        store = OrgStore(":memory:")
        runtime = AgentRuntime(ProviderPool([ProviderConfig(name="mock", model="mock-1")]),
                               ToolRegistry(), store, allow_simulated=True)
        spec = AgentSpec(role="qa:runner", dept="qa", mission_id="m")
        # متجر مكسور عمدًا — السجل يبتلع الخطأ
        store.add_agent_run = lambda **kw: (_ for _ in ()).throw(  # type: ignore[method-assign]
            RuntimeError("مخزن مكسور"))
        out = runtime.ask_json(spec, "أجب JSON")
        assert out.success is True


class TestDeptFailurePaths:
    @pytest.fixture()
    def org_store(self) -> OrgStore:
        return OrgStore(":memory:")

    @pytest.fixture()
    def mission(self, org_store: OrgStore) -> Mission:
        return org_store.create_mission(Mission(title="t", objective="o"))

    def test_requirements_failure_raises(self, org_store: OrgStore) -> None:
        from src.org.departments import DepartmentError, RequirementsOffice

        class BoomPool(ProviderPool):
            def complete_with_fallback(self, messages, **kwargs):  # type: ignore[override]
                raise ProviderError("ميت")

        runtime = AgentRuntime(BoomPool(), ToolRegistry(), org_store)
        office = RequirementsOffice(runtime)
        m = org_store.create_mission(Mission(title="t", objective="o"))
        with pytest.raises(DepartmentError, match="المتطلبات"):
            office.run(MissionContext(mission=m))

    def test_intel_targets_fallback(self, tmp_path: Path,
                                    org_store: OrgStore) -> None:
        """هدف بلا كلمات مطابقة → ترشيح احتياطي حتمي للملفات غير الاختبارية."""
        (tmp_path / "core.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "test_core.py").write_text("def test_x():\n    pass\n",
                                               encoding="utf-8")
        m = org_store.create_mission(Mission(
            title="t", objective="شيء غير مطابق إطلاقًا", repo_path=str(tmp_path)))
        pool = ProviderPool([ProviderConfig(name="mock", model="mock-1")])
        runtime = AgentRuntime(pool, ToolRegistry(), org_store, allow_simulated=True)
        from src.org.security import InjectionGuard
        intel = RepoIntelDept(runtime, InjectionGuard())
        out = intel.run(MissionContext(mission=m))
        assert out["targets"] == ["core.py"]

    def test_dev_requires_worktree(self, org_store: OrgStore) -> None:
        from src.org.departments import DevelopmentDept, DepartmentError
        m = org_store.create_mission(Mission(title="t", objective="o"))
        dev = DevelopmentDept(AgentRuntime(ProviderPool([ProviderConfig(name="mock", model="mock-1")]),
                                           ToolRegistry(), org_store, allow_simulated=True))
        with pytest.raises(DepartmentError, match="نسخة عمل"):
            dev.run(MissionContext(mission=m))

    def test_qa_baseline_skipped_without_repo(self, org_store: OrgStore) -> None:
        from src.org.departments import QADept
        from src.org.sandbox import WorkspaceRunner
        m = org_store.create_mission(Mission(title="t", objective="o"))
        qa = QADept(WorkspaceRunner(), org_store)
        out = qa.baseline(MissionContext(mission=m))
        assert out["status"] == "skipped"

    def test_qa_patched_requires_worktree(self, org_store: OrgStore) -> None:
        from src.org.departments import DepartmentError, QADept
        from src.org.sandbox import WorkspaceRunner
        m = org_store.create_mission(Mission(title="t", objective="o"))
        qa = QADept(WorkspaceRunner(), org_store)
        with pytest.raises(DepartmentError, match="نسخة عمل"):
            qa.patched(MissionContext(mission=m))

    def test_release_pr_fallback_text(self, org_store: OrgStore,
                                      tmp_path: Path) -> None:
        """فشل نموذج الإصدار → نص طلب سحب احتياطي معلن لا صمت."""
        from src.org.departments import DevelopmentDept, ReleaseDept

        class BoomPool(ProviderPool):
            def complete_with_fallback(self, messages, **kwargs):  # type: ignore[override]
                raise ProviderError("ميت")

        ops = OpsStore(":memory:")
        release = ReleaseDept(
            AgentRuntime(BoomPool(), ToolRegistry(), org_store),
            org_store, ops, tmp_path / "out")
        m = org_store.create_mission(Mission(title="مهمة", objective="هدف"))
        ctx = MissionContext(mission=m)
        ctx.diff_text = "--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-x\n+y\n"
        pr = release._pr_text(ctx)
        assert pr["pr_title"] == "org: مهمة"
        assert len(pr["pr_body_sections"]) == 5

    def test_function_hint_fallback_words(self) -> None:
        from src.org.departments import DevelopmentDept
        assert DevelopmentDept._function_hint("split the input", "m.py") \
            == "split"
        assert DevelopmentDept._function_hint("غير مطابق", "parser.py") \
            == "parser"


class TestTaskResultValidation:
    def test_output_must_be_dict(self) -> None:
        with pytest.raises(ValueError):
            TaskResult(task_id="t", dept="qa", status="done",
                       output="not-dict")  # type: ignore[arg-type]

    def test_task_spec_to_dict(self) -> None:
        spec = TaskSpec(mission_id="m", dept="qa", kind="test",
                        description="d", deps=["a"], params={"k": 1},
                        id="org-t-1")
        data = spec.to_dict()
        assert data["id"] == "org-t-1" and data["deps"] == ["a"]


def test_complete_rejects_simulated_provider_by_default() -> None:
    store = OrgStore(":memory:")
    runtime = AgentRuntime(
        ProviderPool([ProviderConfig(name="mock", model="mock-1")]),
        ToolRegistry(),
        store,
    )
    spec = AgentSpec(role="qa:runner", dept="qa", mission_id="m", max_retries=0)

    with pytest.raises(ProviderError, match="simulated provider response rejected"):
        runtime.complete(spec, "أجب")
