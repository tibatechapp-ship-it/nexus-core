"""Failure-path tests for coder review, evaluation and container isolation."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from src.coder.container_sandbox import ContainerSandboxError, run_in_container
from src.coder.evaluation import EvaluationError, _apply_task, _digest_expected, _safe_path, evaluate_tasks
from src.coder.reviewer import ReviewError, review_patch


def verdict(**kw):
    data = {"decision":"approve","summary":"Evidence supports the patch.","findings":[],
            "tests_required":["pytest -q"],"confidence":0.9}
    data.update(kw)
    return data


@pytest.mark.asyncio
async def test_review_async_wrapped_json_is_independent():
    async def provider(prompt):
        assert "PATCH:" in prompt and "EVIDENCE:" in prompt
        return {"ok":True,"reply":"result: "+json.dumps(verdict())}
    out = await review_patch("diff","tests passed",provider,author_provider_id="a",reviewer_provider_id="b")
    assert out["decision"] == "approve" and out["independent"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("patch","evidence","a","b","msg"),[
    ("","","a","b","empty"),("x"*80001,"","a","b","size limit"),
    ("x","y"*40001,"a","b","size limit"),("x","","","b","IDs are required"),
    ("x","","Model","model","distinct")])
async def test_review_input_guards(patch,evidence,a,b,msg):
    with pytest.raises(ReviewError,match=msg):
        await review_patch(patch,evidence,lambda _:verdict(),author_provider_id=a,reviewer_provider_id=b)


@pytest.mark.asyncio
@pytest.mark.parametrize(("reply","msg"),[
    ("no json","JSON object"),("{broken}","invalid JSON"),
    ({"ok":False,"error":"offline"},"provider failed"),({"decision":"bad"},"decision"),
    (verdict(summary=" "),"summary"),(verdict(findings="bad"),"findings"),
    (verdict(findings=[{"severity":"bad"}]),"severity"),
    (verdict(findings=[{"severity":"low","file":"a","issue":1,"evidence":"e"}]),"requires"),
    (verdict(findings=[{"severity":"low","file":"a","issue":"i","evidence":"e","line":0}]),"line"),
    (verdict(tests_required="pytest"),"tests_required"),
    (verdict(tests_required=["x"*501]),"tests_required"),
    (verdict(confidence=True),"confidence"),(verdict(confidence=2),"confidence")])
async def test_review_rejects_malformed_verdict(reply,msg):
    with pytest.raises(ReviewError,match=msg):
        await review_patch("patch","evidence",lambda _:reply,author_provider_id="a",reviewer_provider_id="b")


@pytest.mark.asyncio
async def test_review_downgrades_high_finding_and_bounds_text():
    out = await review_patch("p","e",lambda _:verdict(findings=[
        {"severity":"high","file":"a.py","issue":"i"*2500,"evidence":"e"*2500,"line":3}]),
        author_provider_id="a",reviewer_provider_id="b")
    assert out["decision"] == "request_changes"
    assert len(out["findings"][0]["issue"]) == 2000


def test_evaluation_fails_closed_and_validates_task_list():
    out=evaluate_tasks([{"id":"x"}])
    assert not out["ok"] and out["tasks_passed"] == 0
    for tasks in ([],None,"bad"):
        with pytest.raises(EvaluationError,match="at least one"):
            evaluate_tasks(tasks)


@pytest.mark.parametrize(("task","msg"),[
    ({"id":"../x","test_command":["pytest"]},"id"),
    ({"id":"x","test_command":[]},"test_command"),
    ({"id":"x","test_command":[""]},"test_command"),
    ({"id":"x","test_command":["z"*4097]},"test_command")])
def test_evaluation_rejects_invalid_metadata(task,msg):
    with pytest.raises(EvaluationError,match=msg):
        evaluate_tasks([task],executor=lambda *a,**k:{"ok":True})


def test_evaluation_expected_digest_gates_execution():
    task={"id":"safe","files":{"src/a.py":"x=1\n"},
          "patches":[{"path":"src/a.py","find":"x=1","replace":"x=1"}],
          "expected_files":{"src/a.py":"x=1\n"},"test_command":["pytest"]}
    calls=[]
    out=evaluate_tasks([task],executor=lambda cmd,root,**kw:(calls.append(cmd) or {"ok":True,"exit_code":0}))
    assert out["ok"] and calls == [["pytest"]]
    task["expected_files"]={"src/a.py":"wrong"}
    out=evaluate_tasks([task],executor=lambda *a,**k:pytest.fail("must not execute"))
    assert out["results"][0]["reason"] == "patch_output_mismatch"


def test_evaluation_rejects_path_traversal_duplicate_find_and_symlink(tmp_path:Path):
    with pytest.raises(EvaluationError,match="unsafe"):
        _safe_path(tmp_path,"../escape.py")
    with pytest.raises(EvaluationError,match="requires files"):
        _apply_task(tmp_path,{"files":[],"patches":[]})
    with pytest.raises(EvaluationError,match="exactly once"):
        _apply_task(tmp_path,{"files":{"a.py":"x=1\nx=1"},
            "patches":[{"path":"a.py","find":"x=1","replace":"x=2"}]})
    outside=tmp_path/"outside.py"; outside.write_text("x=1")
    (tmp_path/"link.py").symlink_to(outside)
    with pytest.raises(EvaluationError,match="regular file"):
        _apply_task(tmp_path,{"files":{},"patches":[
            {"path":"link.py","find":"x=1","replace":"x=2"}]})
    assert _digest_expected(tmp_path,{}) == (True,[])


def test_container_sandbox_requires_opt_in_approval_digest(tmp_path:Path,monkeypatch):
    image="registry.example/runner@sha256:"+"a"*64
    with pytest.raises(ContainerSandboxError,match="disabled"):
        run_in_container(["pytest"],tmp_path,image=image)
    monkeypatch.setenv("NEXUS_ENABLE_CONTAINER_SANDBOX","1")
    with pytest.raises(ContainerSandboxError,match="approval"):
        run_in_container(["pytest"],tmp_path,image=image,enabled=True)
    with pytest.raises(ContainerSandboxError,match="digest"):
        run_in_container(["pytest"],tmp_path,image="latest",enabled=True,approved=True)


@pytest.mark.parametrize(("kw","msg"),[
    ({"memory":"64m"},"between 128m"),({"memory":"1tb"},"integer"),
    ({"cpus":"0"},"invalid CPU"),({"cpus":"9"},"between 0.1"),
    ({"pids_limit":0},"pids_limit"),({"pids_limit":257},"pids_limit"),
    ({"command":[]},"non-empty argv"),({"command":["x","y"*4097]},"argument limits")])
def test_container_sandbox_rejects_resource_limits(tmp_path:Path,monkeypatch,kw,msg):
    monkeypatch.setenv("NEXUS_ENABLE_CONTAINER_SANDBOX","1")
    args={"command":["pytest"],"memory":"1g","cpus":"2","pids_limit":64}; args.update(kw)
    with pytest.raises(ContainerSandboxError,match=msg):
        run_in_container(args.pop("command"),tmp_path,image="runner@sha256:"+"b"*64,
                         enabled=True,approved=True,**args)
