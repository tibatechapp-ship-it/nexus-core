"""Nexus CLI — الواجهة الموحدة لـ nexus-core.

الأوامر:
    nexus chat                      محادثة تفاعلية
    nexus ask "<question>"          سؤال واحد
    nexus review <path>             مراجعة مشروع
    nexus council "<topic>"         مجلس الحكماء
    nexus delegate <agent> "<task>" تفويض وكيل
    nexus sessions                  قائمة الجلسات
    nexus skills                    قائمة المهارات
    nexus skill <name>              عرض مهارة
    nexus status                    حالة النظام
    nexus agents                    قائمة الوكلاء
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path
from typing import Sequence

# إعداد المسار
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from src import __version__
from src.sessions.manager import SessionManager
from src.skills.loader import SkillLoader


_AGENT_SCAFFOLD = frozenset({"base", "registry", "state", "sub_agent", "communication", "metrics"})
"""وحدات بنية تحتية في src/agents — ليست وكلاء (نفس منطق nexus_agent)."""

_REVIEW_SCRIPT = Path(tempfile.gettempdir()) / "run_5_agents.py"
"""سكريبت مراجعة الـ5 وكلاء الذي ينسخه ``nexus review``.

يُبنى على ``tempfile.gettempdir()`` (يحترم ``$TMPDIR``) فلا يثبّت مسار Termux
على منصّات أخرى — على Termux يعطي نفس المسار السابق تمامًا.
"""
_REVIEW_DYN = Path(tempfile.gettempdir()) / "review_dynamic.py"
"""مخرَج ``nexus review`` المؤقت (السكريبت بعد توجيهه إلى المشروع)."""


def cmd_status(args: argparse.Namespace) -> int:
    """يعرض حالة النظام."""
    print("=" * 60)
    print("  🔍 Nexus-Core Status")
    print("=" * 60)
    print()
    
    # Sessions
    sm = SessionManager()
    sessions = sm.list_sessions(limit=5)
    print(f"📁 Sessions: {len(sessions)} (آخر 5)")
    for s in sessions:
        print(f"   • {s.id} | {s.title[:40]} | {s.agent}")
    print()
    
    # Skills
    sl = SkillLoader()
    skills = sl.list_skills()
    print(f"🎯 Skills: {len(skills)}")
    for name in skills:
        print(f"   • {name}")
    print()
    
    # OllamaBackend
    try:
        from src.core.ollama_backend import OllamaBackend
        b = OllamaBackend()
        print("🤖 Backend: OllamaBackend")
        print(f"   Keys: {len(b.keys)}")
        print(f"   Models: {len(b.models)}")
        for m in b.models:
            print(f"      • {m}")
    except Exception as e:
        print(f"🤖 Backend: ❌ {e}")
    print()
    
    # Agents
    try:
        agents_dir = ROOT / "src" / "agents"
        agents = sorted(
            f.stem for f in agents_dir.glob("*.py")
            if not f.stem.startswith("_") and f.stem not in _AGENT_SCAFFOLD
        )
        print(f"👥 Agents: {len(agents)}")
        for a in agents[:10]:
            print(f"   • {a}")
        if len(agents) > 10:
            print(f"   ... و {len(agents) - 10} آخرين")
    except Exception as e:
        print(f"👥 Agents: ❌ {e}")
    
    print()
    print("=" * 60)
    return 0


def cmd_agents(args: argparse.Namespace) -> int:
    """يعرض كل الوكلاء."""
    agents_dir = ROOT / "src" / "agents"
    agents = sorted(
        f.stem for f in agents_dir.glob("*.py")
        if not f.stem.startswith("_") and f.stem not in _AGENT_SCAFFOLD
    )
    print(f"👥 {len(agents)} وكيل:")
    for a in agents:
        print(f"  • {a}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    """سؤال سريع عبر وكيل واحد."""
    from src.core.ollama_backend import OllamaBackend
    from src.agents.analyst import AnalystAgent
    
    backend = OllamaBackend()
    agent = AnalystAgent(backend)
    
    question = " ".join(args.question)
    result = agent.run(question)
    
    # اعرض النتيجة
    if hasattr(result, "output"):
        print(result.output)
    else:
        print(result)
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    """محادثة تفاعلية."""
    from src.core.ollama_backend import OllamaBackend
    
    print("=" * 60)
    print("  💬 Nexus Chat (اكتب 'exit' للخروج)")
    print("=" * 60)
    print()
    
    # ابدأ جلسة
    sm = SessionManager()
    session = sm.create(title="Interactive chat", agent=args.agent or "analyst")
    print(f"📁 Session: {session.id}")
    print()
    
    # Backend
    backend = OllamaBackend()
    
    # الوكيل
    from src.agents.analyst import AnalystAgent
    from src.agents.architect import ArchitectAgent
    from src.agents.reviewer import ReviewerAgent
    from src.agents.coder import CoderAgent
    
    AGENTS = {
        "analyst": AnalystAgent,
        "architect": ArchitectAgent,
        "reviewer": ReviewerAgent,
        "coder": CoderAgent,
    }
    
    agent_cls = AGENTS.get(session.agent, AnalystAgent)
    agent = agent_cls(backend)
    
    while True:
        try:
            prompt = input("أنت> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        
        if not prompt:
            continue
        if prompt.lower() in ("exit", "quit", "خروج"):
            break
        
        # أضف للجلسة
        session.add_message("user", prompt)
        
        # شغّل الوكيل
        try:
            result = agent.run(prompt)
            output = result.output if hasattr(result, "output") else str(result)
            print(f"\n🤖 [{session.agent}]\n{output}\n")
            session.add_message("assistant", output)
            sm.save(session)
        except Exception as e:
            print(f"❌ {e}")
    
    print(f"\n📁 تم حفظ الجلسة: {session.id}")
    print(f"   استئناف: nexus chat --session {session.id}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """مراجعة مشروع عبر 5 وكلاء."""
    import subprocess

    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"❌ المسار غير موجود: {path}")
        return 1

    # استخدم السكريبت الموجود (مسار مؤقت محمول — انظر _REVIEW_SCRIPT)
    script = _REVIEW_SCRIPT
    if script.exists():
        content = script.read_text()
        # وجّه السكريبت إلى المشروع المطلوب: استبدل أي سطر TARGET = Path("...")
        content = re.sub(
            r'^TARGET = Path\(".*"\)',
            lambda _m: f'TARGET = Path("{path}")',
            content,
            count=1,
            flags=re.MULTILINE,
        )
        tmp_script = _REVIEW_DYN
        tmp_script.write_text(content)
        return subprocess.call(["python3", "-u", str(tmp_script)])
    else:
        print("❌ سكريبت المراجعة غير موجود")
        return 1


def cmd_sessions(args: argparse.Namespace) -> int:
    """يعرض الجلسات."""
    sm = SessionManager()
    sessions = sm.list_sessions(limit=50)
    
    if not sessions:
        print("📁 لا توجد جلسات")
        return 0
    
    print(f"📁 {len(sessions)} جلسة:")
    print()
    for s in sessions:
        print(f"  {s.id}")
        print(f"    {s.title[:60]}")
        print(f"    {s.agent} | {s.updated_at[:19]}")
        print(f"    {len(s.messages)} رسالة")
        print()
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    """يعرض المهارات."""
    sl = SkillLoader()
    skills = sl.list_skills()
    
    if not skills:
        print("🎯 لا توجد مهارات")
        return 0
    
    print(f"🎯 {len(skills)} مهارة:")
    print()
    for name in skills:
        skill = sl.load(name)
        if skill:
            print(f"  • {name}: {skill.description[:60]}")
    return 0


def cmd_skill(args: argparse.Namespace) -> int:
    """يعرض مهارة كاملة."""
    sl = SkillLoader()
    skill = sl.load(args.name)
    
    if not skill:
        print(f"❌ المهارة غير موجودة: {args.name}")
        print(f"   المتاح: {', '.join(sl.list_skills())}")
        return 1
    
    print(skill.content)
    return 0


def cmd_delegate(args: argparse.Namespace) -> int:
    """يفوّض وكيلاً بمهمة."""
    from src.core.ollama_backend import OllamaBackend
    
    agent_name = args.agent
    task = " ".join(args.task)
    
    # ابحث عن الوكيل
    try:
        mod = __import__(f"src.agents.{agent_name}", fromlist=["*"])
    except ImportError:
        print(f"❌ الوكيل غير موجود: {agent_name}")
        return 1
    
    # اعثر على class
    cls = None
    for attr in dir(mod):
        if attr.endswith("Agent") and not attr.startswith("_"):
            cls = getattr(mod, attr)
            break
    
    if cls is None:
        print(f"❌ لا يوجد class Agent في {agent_name}")
        return 1
    
    backend = OllamaBackend()
    agent = cls(backend)
    
    print(f"🤖 {agent_name}: {task}")
    print()
    result = agent.run(task)
    print(result.output if hasattr(result, "output") else result)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """نقطة الدخول الرئيسية."""
    parser = argparse.ArgumentParser(
        prog="nexus",
        description="Nexus-Core CLI — واجهة موحدة لوكلاء nexus-core",
    )
    parser.add_argument("-v", "--version", action="version", version=f"nexus-core {__version__}")
    
    sub = parser.add_subparsers(dest="command", help="الأوامر المتاحة")
    
    # status
    p_status = sub.add_parser("status", help="حالة النظام")
    p_status.set_defaults(func=cmd_status)
    
    # agents
    p_agents = sub.add_parser("agents", help="قائمة الوكلاء")
    p_agents.set_defaults(func=cmd_agents)
    
    # ask
    p_ask = sub.add_parser("ask", help="سؤال سريع")
    p_ask.add_argument("question", nargs="+", help="السؤال")
    p_ask.set_defaults(func=cmd_ask)
    
    # chat
    p_chat = sub.add_parser("chat", help="محادثة تفاعلية")
    p_chat.add_argument("--agent", default="analyst", help="الوكيل")
    p_chat.add_argument("--session", help="استئناف جلسة")
    p_chat.set_defaults(func=cmd_chat)
    
    # review
    p_review = sub.add_parser("review", help="مراجعة مشروع")
    p_review.add_argument("path", help="مسار المشروع")
    p_review.set_defaults(func=cmd_review)
    
    # sessions
    p_sessions = sub.add_parser("sessions", help="قائمة الجلسات")
    p_sessions.set_defaults(func=cmd_sessions)
    
    # skills
    p_skills = sub.add_parser("skills", help="قائمة المهارات")
    p_skills.set_defaults(func=cmd_skills)
    
    # skill
    p_skill = sub.add_parser("skill", help="عرض مهارة")
    p_skill.add_argument("name", help="اسم المهارة")
    p_skill.set_defaults(func=cmd_skill)
    
    # delegate
    p_delegate = sub.add_parser("delegate", help="تفويض وكيل")
    p_delegate.add_argument("agent", help="اسم الوكيل")
    p_delegate.add_argument("task", nargs="+", help="المهمة")
    p_delegate.set_defaults(func=cmd_delegate)
    
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
