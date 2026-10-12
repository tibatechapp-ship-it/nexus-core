#!/usr/bin/env python3
"""Unified Bot — NovaMind + HiveLoop"""

from __future__ import annotations
import asyncio
import subprocess
import logging
import os
import sys
import time
from datetime import datetime, timezone, time as time_of_day
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

# HiveLoop imports
from hive.runtime.pool import AgentPool
from hive.runtime.base_agent import Task
from hive.runtime.adapter import AdapterRegistry
from hive.memory.task_memory import TaskMemory
from hive.ops.morning_cycle import MorningCycle
from hive.orchestration.orchestrator import Orchestrator, Stage
from hive.security.fingerprint import Fingerprint

# NovaMind imports
from novamind.core.company.supreme import SupremeCouncil
from novamind.core.company.reports import ReportGenerator
from novamind.core.company.admin import AdminCommands
from novamind.core.company.insights import InsightsEngine

# Git & Agents control
from hive.interface import git_control as _gc

# ═══ رسائل الترحيب ═══
try:
    from hive.interface.welcome_messages import (
        WELCOME_MESSAGE as _WELCOME_MSG,
        QUICK_COMMANDS as _QUICK_CMD,
        TOOLS_MESSAGE as _TOOLS_MSG,
        NEW_USER_WELCOME as _NEW_USER_MSG,
        THINKING as _THINKING_MSG,
    )
    _HAS_WELCOME = True
except Exception:
    _HAS_WELCOME = False
    _WELCOME_MSG = "🌟 أهلاً بك في NovaMind"
    _QUICK_CMD = "استخدم /panel"
    _TOOLS_MSG = "الأدوات متاحة عبر /tools"
    _NEW_USER_MSG = "مرحباً!"
    _THINKING_MSG = "🤔"

from hive.interface import agents_runner as _ar

# ═══ جديد: الأدوات الذكية ═══
try:
    import hive.tools.builtin  # يسجّل الأدوات تلقائياً
    from hive.agents import get_tool_agent as _get_tool_agent
    _HAS_TOOLS = True
except Exception as _e:
    _HAS_TOOLS = False
    _get_tool_agent = None
    print(f"⚠️ Tools init failed: {_e}")


# ═══ جديد: الذاكرة الدلالية ═══
try:
    from hive.memory import get_memory as _get_memory
    _HAS_MEMORY = True
except Exception:
    _HAS_MEMORY = False
    _get_memory = None


# ═══ جديد: موحّد المزودين والتحليلات ═══
try:
    from hive.providers.registry import get_registry as _get_provider_registry
    _HAS_PROVIDERS = True
except Exception as _e:
    _HAS_PROVIDERS = False
    _get_provider_registry = None

try:
    from hive.analytics.cost_tracker import get_costs as _get_costs
    _HAS_COSTS = True
except Exception:
    _HAS_COSTS = False

try:
    from hive.analytics.eval_tracker import get_evals as _get_evals
    _HAS_EVALS = True
except Exception:
    _HAS_EVALS = False

try:
    from hive.security.hallucination import HallucinationDetector as _HallucinationDetector
    _HAS_HALLUC = True
except Exception:
    _HAS_HALLUC = False


# ═══════════════════════════════════════════════════════════
#  HiveLoop-X Security: Redact secrets BEFORE any logging
# ═══════════════════════════════════════════════════════════
try:
    from hive.security.log_redaction import install as _install_redaction
    _install_redaction()
except Exception:
    pass

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("UnifiedBot")

# Global instances
_supreme = None
_reporter = None
_admin = None
_insights = None

def get_nm():
    """Get or create NovaMind instances."""
    global _supreme, _reporter, _admin, _insights
    if _supreme is None:
        _supreme = SupremeCouncil(verbose=False)
        _supreme.restore_from_registry()
        _reporter = ReportGenerator(_supreme)
        _admin = AdminCommands(_supreme)
        _insights = InsightsEngine(_supreme)
    return _supreme, _reporter, _admin, _insights


def token():
    t = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not t:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")
    return t


# ========== GENERAL ==========

# SHELL_V3
async def _send_long(message, text: str, max_len: int = 3800):
    """يرسل نصًا طويلًا مقسّمًا."""
    if len(text) <= max_len:
        try:
            await message.reply_text(text, parse_mode="Markdown")
        except Exception:
            await message.reply_text(text)
        return
    # قسّم
    parts = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            parts.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        parts.append(current)

    for i, p in enumerate(parts):
        header = f"_(جزء {i+1}/{len(parts)})_\n" if len(parts) > 1 else ""
        try:
            await message.reply_text(header + p, parse_mode="Markdown")
        except Exception:
            await message.reply_text(header + p)


async def cmd_start(update, context):
    """رسالة الترحيب."""
    user = update.effective_user
    name = user.first_name if user else "صديقي"

    try:
        await update.message.reply_text(
            f"مرحباً *{name}* 👋\n\n" + _WELCOME_MSG,
            parse_mode="Markdown",
        )
    except Exception:
        await update.message.reply_text(_WELCOME_MSG)



async def cmd_help(update, context):
    """المساعدة الكاملة."""
    try:
        await update.message.reply_text(_QUICK_CMD, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(_QUICK_CMD)



async def cmd_hive_status(update, context):
    try:
        reg = AdapterRegistry()
        info = reg.info()
        mem = TaskMemory()
        s = mem.summary()
        text = (
            "HiveLoop Status\n\n"
            f"Agents: {info['total']}\n"
            f"Total tasks: {s['total_tasks']}\n"
            f"Success: {s['successes']} / Failures: {s['failures']}\n"
            f"Rate: {s['success_rate']}\n"
            f"Avg: {s['avg_duration']}s\n"
            f"Agents seen: {s['agents_seen']}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_hive_list(update, context):
    try:
        reg = AdapterRegistry()
        agents = reg.list_agents()
        chunk = 40
        for i in range(0, len(agents), chunk):
            part = agents[i:i+chunk]
            text = f"Agents ({i+1}-{min(i+chunk, len(agents))}/{len(agents)}):\n"
            text += "\n".join(f"- {a}" for a in part)
            await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_hive_recent(update, context):
    try:
        mem = TaskMemory()
        rows = mem.recent(10)
        if not rows:
            await update.message.reply_text("No recent tasks")
            return
        text = f"Last {len(rows)}:\n"
        for r in rows:
            status = "OK" if r["status"] == "success" else "FAIL"
            text += f"[{status}] {r['agent_id']} - {r['duration_seconds']}s\n"
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_hive_stats(update, context):
    try:
        mem = TaskMemory()
        stats = mem.agent_stats()
        if not stats:
            await update.message.reply_text("No stats yet")
            return
        text = f"Top {min(15, len(stats))}:\n"
        for s in stats[:15]:
            total = s["total_runs"] or 1
            rate = s["successes"] / total
            text += f"{s['agent_id']}: {total} runs, rate={rate:.2f}\n"
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_hive_morning(update, context):
    await update.message.reply_text("Running morning cycle...")
    try:
        cycle = MorningCycle(objective="Telegram morning cycle")
        result = await cycle.run()
        text = (
            f"Morning Cycle Done\n"
            f"Status: {result.status}\n"
            f"Duration: {result.duration_seconds}s\n"
            f"Stages: {len(result.stages)}\n"
        )
        total = sum(len(s["results"]) for s in result.stages)
        ok = sum(1 for s in result.stages for r in s["results"] if r["status"] == "success")
        text += f"Agents: {ok}/{total}"
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_hive_run(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /hive_run <agent> <task>")
        return
    agent = context.args[0]
    task_text = " ".join(context.args[1:])
    await update.message.reply_text(f"Running {agent}...")
    try:
        pool = AgentPool(max_concurrent=1)
        task = Task(objective=task_text)
        result = await pool.run_one(agent, task)
        text = (
            f"Agent: {result.agent_id}\n"
            f"Status: {result.status}\n"
            f"Duration: {result.duration_seconds}s\n"
        )
        if result.output:
            out = str(result.output)[:800]
            text += f"\nOutput:\n{out}"
        if result.error:
            text += f"\nError: {result.error}"
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_hive_parallel(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /hive_parallel <a,b,c> <task>")
        return
    agents = [a.strip() for a in context.args[0].split(",")]
    task_text = " ".join(context.args[1:])
    await update.message.reply_text(f"Running {len(agents)} agents...")
    try:
        pool = AgentPool(max_concurrent=10)
        task = Task(objective=task_text)
        jobs = [(a, task) for a in agents]
        results = await pool.run_many(jobs)
        mem = TaskMemory()
        for r in results:
            r.task_type = "telegram"
            r.objective = task_text
            mem.save(r)
        text = f"Results ({len(results)}):\n"
        for r in results:
            status = "OK" if r.status == "success" else "FAIL"
            text += f"[{status}] {r.agent_id} - {r.duration_seconds}s\n"
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_hive_workflow(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /hive_workflow <task> --stages s1:a,b;s2:c")
        return
    parts = " ".join(context.args).split("--stages")
    objective = parts[0].strip()
    stages_str = parts[1].strip() if len(parts) > 1 else "analysis:analyzer;quality:code_review;security:security"
    await update.message.reply_text(f"Workflow: {objective}")
    try:
        stage_list = []
        for s in stages_str.split(";"):
            p = s.split(":")
            if len(p) == 2:
                name = p[0].strip()
                agents = [a.strip() for a in p[1].split(",")]
                stage_list.append(Stage(name, agents, mode="parallel"))
        orch = Orchestrator()
        task = Task(objective=objective)
        result = await orch.run_workflow(task, stage_list)
        text = f"Status: {result.status}\nDuration: {result.duration_seconds}s\n"
        for stage in result.stages:
            text += f"\n{stage['name']}:\n"
            for r in stage["results"]:
                ok = "OK" if r["status"] == "success" else "FAIL"
                text += f"  [{ok}] {r['agent']} ({r['duration']}s)\n"
        await update.message.reply_text(text[:4000])
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


# ========== NOVAMIND ==========

async def cmd_nm_status(update, context):
    await update.message.reply_text("...")
    try:
        _, rep, _, _ = get_nm()
        await update.message.reply_text(rep.status_report()[:4000])
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_agents(update, context):
    await update.message.reply_text("...")
    try:
        _, rep, _, _ = get_nm()
        await update.message.reply_text(rep.agents_report()[:4000])
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_leaderboard(update, context):
    await update.message.reply_text("...")
    try:
        _, rep, _, _ = get_nm()
        await update.message.reply_text(rep.leaderboard_report()[:4000])
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_report(update, context):
    await update.message.reply_text("...")
    try:
        _, rep, _, _ = get_nm()
        msg = rep.full_report()
        for i in range(0, len(msg), 3900):
            await update.message.reply_text(msg[i:i+3900])
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_evaluate(update, context):
    await update.message.reply_text("...")
    try:
        s, _, _, _ = get_nm()
        r = s.evaluate_daily_targets()
        text = "Evaluation:\n"
        text += f"Total: {r.get('total_evaluated', 0)}\n"
        text += f"Coins: {r.get('total_coins_delta', 0)}\n"
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_evolve(update, context):
    await update.message.reply_text("...")
    try:
        s, _, _, _ = get_nm()
        r = s.evolve()
        await update.message.reply_text(f"Evolve: {str(r)[:1500]}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_schedule(update, context):
    chat = update.effective_chat.id
    jq = context.application.job_queue
    if jq is None:
        await update.message.reply_text("JobQueue not available")
        return
    for job in jq.jobs():
        if job.name and job.name.startswith(f"nm_{chat}_"):
            job.schedule_removal()
    for hour, name in [(8, "morning"), (12, "midday"), (18, "evening"), (22, "night")]:
        jq.run_daily(
            send_nm_scheduled,
            time=time_of_day(hour=hour, minute=0),
            data={"type": name, "chat_id": chat},
            name=f"nm_{chat}_{name}",
        )
    await update.message.reply_text(
        "Scheduled: 08:00, 12:00, 18:00, 22:00"
    )


async def send_nm_scheduled(context):
    job = context.job
    rtype = job.data.get("type")
    chat = job.data.get("chat_id")
    try:
        _, rep, _, _ = get_nm()
        fn = {
            "morning": rep.morning_report,
            "midday": rep.midday_report,
            "evening": rep.evening_report,
            "night": rep.night_report,
        }.get(rtype)
        if fn:
            await context.bot.send_message(chat_id=chat, text=fn()[:4000])
    except Exception as e:
        logger.error(f"scheduled report error: {e}")


async def cmd_nm_mission(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /nm_mission <spec> <task>")
        return
    spec = context.args[0]
    task = " ".join(context.args[1:])
    await update.message.reply_text(f"Mission: {spec}...")
    try:
        s, _, _, _ = get_nm()
        if not any(x.specialty == spec for x in s.soldiers):
            s.recruit(spec, f"You are a {spec}.")
        r = await s.execute_mission(spec, task)
        if r.get("status") == "success":
            resp = r.get("response", "")[:1500]
            await update.message.reply_text(f"OK\n\n{resp}")
        else:
            await update.message.reply_text(f"Failed: {str(r)[:500]}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_recruit(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /nm_recruit <spec>")
        return
    try:
        s, _, _, _ = get_nm()
        info = s.recruit(context.args[0], f"You are a {context.args[0]}.")
        await update.message.reply_text(f"Recruited: {info.get('id')} | {info.get('specialty')}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_develop(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /nm_develop <id> <specialty>")
        return
    try:
        _, _, admin, _ = get_nm()
        r = admin.develop_soldier(context.args[0], new_specialty=context.args[1])
        await update.message.reply_text(f"Developed: {str(r)[:500]}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_upgrade(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /nm_upgrade <id>")
        return
    try:
        _, _, admin, _ = get_nm()
        r = admin.upgrade_soldier(context.args[0])
        await update.message.reply_text(f"Upgraded: {str(r)[:500]}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_retrain(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /nm_retrain <id>")
        return
    try:
        _, _, admin, _ = get_nm()
        r = admin.retrain_soldier(context.args[0])
        await update.message.reply_text(f"Retrained: {str(r)[:500]}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_purge(update, context):
    try:
        _, _, admin, _ = get_nm()
        trust = float(context.args[0]) if context.args else 0.3
        r = admin.purge_weak(trust)
        await update.message.reply_text(f"Purged: {r.get('count', 0)}, Remaining: {r.get('remaining', 0)}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_clone(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /nm_clone <id> [count]")
        return
    try:
        _, _, admin, _ = get_nm()
        count = int(context.args[1]) if len(context.args) > 1 else 3
        r = admin.clone_elite(context.args[0], count)
        await update.message.reply_text(f"Cloned: {str(r)[:500]}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_insights(update, context):
    try:
        _, _, _, ins = get_nm()
        data = ins.analyze()
        msg = ins.format_insights(data)
        await update.message.reply_text(msg[:4000])
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_nm_inject_vaccine(update, context):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /nm_inject_vaccine <spec> <threat> <defense>")
        return
    try:
        _, _, admin, _ = get_nm()
        spec = context.args[0]
        threat = context.args[1]
        defense = " ".join(context.args[2:])
        r = admin.inject_vaccine(spec, threat, defense)
        await update.message.reply_text(f"Injected: {str(r)[:500]}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_echo(update, context):
    """الرد الذكي عبر AgentRouter (agents -> LLM router -> fallback)."""
    text = (update.message.text or "").strip()
    if not text:
        return

    try:
        await update.message.chat.send_action("typing")
    except Exception:
        pass

    try:
        from hive.interface.agent_router import route_message
        result = await route_message(text, context={
            "user_id": update.effective_user.id if update.effective_user else None,
            "chat_id": update.effective_chat.id if update.effective_chat else None,
        })

        icons = {"agent": "[agent]", "llm": "[llm]", "fallback": "[info]"}
        icon = icons.get(result["source"], "")
        meta = result.get("meta", {})

        footer_parts = []
        if result["source"] == "agent":
            footer_parts.append(f"agent: {meta.get('agent', '?')}")
            subs = meta.get("sub_agents") or []
            if subs:
                footer_parts.append(f"sub: {', '.join(subs[:2])}")
        elif result["source"] == "llm":
            footer_parts.append(f"provider: {meta.get('provider', '?')}")
        duration = meta.get("duration_ms", 0)
        if duration:
            footer_parts.append(f"{duration}ms")

        footer = chr(10) + chr(10) + "_" + " | ".join(footer_parts) + "_" if footer_parts else ""
        body = result["text"][:3500]

        await update.message.reply_text(f"{icon} {body}{footer}")
    except Exception as e:
        logger.exception("cmd_echo failed")
        await update.message.reply_text(f"Error: {str(e)[:200]}")




async def cmd_shell(update, context):
    """ينفّذ أمر shell آمن (للمسؤول فقط)."""
    import os
    from hive.tools.shell_v2 import run_command, format_result, list_commands

    admin_id = os.getenv("TELEGRAM_ADMIN_ID", "0")
    user_id = update.effective_user.id if update.effective_user else 0
    try:
        allowed = [int(admin_id)] if admin_id and admin_id != "0" else []
    except (ValueError, TypeError):
        allowed = []

    if user_id not in allowed:
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return

    if not context.args:
        presets = list_commands()
        lines = ["🔧 *Shell v2 — أوامر جاهزة:*", ""]
        for p in presets[:25]:
            lines.append(f"  • `{p}`")
        lines.append("")
        lines.append("*أو أمر مباشر:*")
        lines.append("`/shell ls /public`")
        lines.append("`/shell df -h`")
        lines.append("⚠️ أوامر خطيرة (rm, sudo) ممنوعة تلقائيًا.")
        await _send_long(update.message, "\n".join(lines))
        return

    cmd = " ".join(context.args)

    try:
        result = run_command(cmd)
    except Exception as e:
        await update.message.reply_text(f"❌ {type(e).__name__}: {str(e)[:300]}")
        return

    text = format_result(result)
    await _send_long(update.message, text)


async def cmd_svc(update, context):
    """حالة supervisor."""
    import os
    from hive.tools.shell_v2 import run_command, format_result
    admin_id = os.getenv("TELEGRAM_ADMIN_ID", "0")
    user_id = update.effective_user.id if update.effective_user else 0
    try:
        allowed = [int(admin_id)] if admin_id and admin_id != "0" else []
    except (ValueError, TypeError):
        allowed = []
    if user_id not in allowed:
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return
    result = run_command("svc_status")
    await _send_long(update.message, format_result(result))


async def cmd_logs(update, context):
    """آخر أسطر من السجل (آمن، محدود)."""
    import os
    from hive.tools.shell_v2 import run_command
    admin_id = os.getenv("TELEGRAM_ADMIN_ID", "0")
    user_id = update.effective_user.id if update.effective_user else 0
    try:
        allowed = [int(admin_id)] if admin_id and admin_id != "0" else []
    except (ValueError, TypeError):
        allowed = []

    if user_id not in allowed:
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return

    # args: [service_name, num_lines]
    args = context.args or []
    num_lines = 20
    log_file = "/var/log/novamind-bot.log"

    if args:
        if args[0].lower() == "supervisor":
            log_file = "/var/log/supervisord.log"
        if len(args) >= 2:
            try:
                num_lines = max(5, min(100, int(args[1])))
            except ValueError:
                pass

    # اقرأ الملف مباشرة
    from pathlib import Path as _P
    p = _P(log_file)
    if not p.exists():
        await update.message.reply_text(f"❌ لا يوجد: {log_file}")
        return

    try:
        content = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return

    last = content[-num_lines:]
    text = f"📜 *{log_file}* (آخر {len(last)} من {len(content)})\n\n```\n" + "\n".join(last) + "\n```"
    await _send_long(update.message, text)


async def cmd_generated(update, context):
    """يعرض الأنظمة المُولَّدة في /public/generated."""
    import os
    admin_id = os.getenv("TELEGRAM_ADMIN_ID", "0")
    user_id = update.effective_user.id if update.effective_user else 0
    try:
        allowed = [int(admin_id)] if admin_id and admin_id != "0" else []
    except (ValueError, TypeError):
        allowed = []

    if user_id not in allowed:
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return

    from pathlib import Path as _Path
    base = _Path("/public/generated")
    if not base.exists():
        await update.message.reply_text("📂 لا يوجد مجلد generated بعد.")
        return

    dirs = sorted([d for d in base.iterdir() if d.is_dir()])
    if not dirs:
        await update.message.reply_text("📂 لا توجد أنظمة مُولَّدة.")
        return

    lines = [f"📦 *الأنظمة المُولَّدة* ({len(dirs)}):", ""]
    for d in dirs:
        py_count = len(list(d.rglob("*.py")))
        manifest = d / ".novamind_manifest.json"
        status = "✅" if manifest.exists() else "⚠️"
        lines.append(f"  {status} `{d.name}` — {py_count} ملف .py")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_verify(update, context):
    """تحقق من سلامة الملفات."""
    try:
        fp = Fingerprint()
        report = fp.verify()
        msg = "Fingerprint Report" + chr(10)
        msg += f"Expected: {report['total_expected']}" + chr(10)
        msg += f"Actual:   {report['total_actual']}" + chr(10)
        msg += chr(10)
        msg += f"Unchanged: {len(report['unchanged'])}" + chr(10)
        msg += f"Modified:  {len(report['modified'])}" + chr(10)
        msg += f"Missing:   {len(report['missing'])}" + chr(10)
        msg += f"New:       {len(report['new'])}" + chr(10)

        if report["critical_violations"]:
            msg += chr(10) + "CRITICAL VIOLATIONS:" + chr(10)
            for c in report["critical_violations"]:
                msg += f"  - {c}" + chr(10)

        if report["modified"]:
            msg += chr(10) + "Modified:" + chr(10)
            for m in report["modified"][:10]:
                msg += f"  ~ {m['path']}" + chr(10)

        await update.message.reply_text(msg[:4000])
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_trust(update, context):
    """اعتمد الحالة الحالية كمرجع جديد (بعد موافقة)."""
    try:
        fp = Fingerprint()
        n = fp.init()
        fp.audit("manual_trust", {"count": n, "user": update.effective_user.id})
        await update.message.reply_text(f"Trusted snapshot saved: {n} files")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")





# __UI_START__
# ═══════════════════════════════════════════════════════════
#  Interactive UI (InlineKeyboards)
# ═══════════════════════════════════════════════════════════

import os as _os

# HiveLoop-X security: redact secrets from all logs
try:
    from hive.security.log_redaction import install as _install_redaction
    _install_redaction()
except Exception:
    pass



def _is_admin(obj):
    """Check if user is admin."""
    admin_id_str = _os.getenv("TELEGRAM_ADMIN_ID", "0")
    try:
        admin_id = int(admin_id_str)
    except (ValueError, TypeError):
        return False
    if hasattr(obj, "effective_user") and obj.effective_user:
        return obj.effective_user.id == admin_id
    if hasattr(obj, "from_user") and obj.from_user:
        return obj.from_user.id == admin_id
    return False


def _main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 حالة النظام", callback_data="menu_status")],
        [InlineKeyboardButton("🛠️ تعديل برمجي (Aider)", callback_data="menu_aider")],
        [InlineKeyboardButton("🤖 الوكلاء", callback_data="menu_agents")],
        [InlineKeyboardButton("📈 التقارير", callback_data="menu_reports")],
        [InlineKeyboardButton("🌐 المزودون", callback_data="menu_providers")],
        [InlineKeyboardButton("🔐 المفاتيح", callback_data="menu_keys")],
        [InlineKeyboardButton("💰 التكاليف", callback_data="menu_costs")],
        [InlineKeyboardButton("📊 التقييمات", callback_data="menu_evals")],
        [InlineKeyboardButton("🌐 المزودون (موحد)", callback_data="menu_providers_v2")],
        [InlineKeyboardButton("🛡️ كشف الهلوسة", callback_data="menu_halluc")],
        [InlineKeyboardButton("🧠 الذاكرة", callback_data="menu_memory")],
        [InlineKeyboardButton("🔍 بحث دلالي", callback_data="menu_recall")],
        [InlineKeyboardButton("📝 حفظ ملاحظة", callback_data="menu_note")],
        [InlineKeyboardButton("🛠️ أدوات ذكية", callback_data="menu_tools")],
    ])


def _status_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💾 القرص", callback_data="cmd_df"),
         InlineKeyboardButton("🧠 الذاكرة", callback_data="cmd_free")],
        [InlineKeyboardButton("⚡ العمليات", callback_data="cmd_ps"),
         InlineKeyboardButton("⏱️ وقت التشغيل", callback_data="cmd_uptime")],
        [InlineKeyboardButton("📝 Git Status", callback_data="cmd_git_status")],
        [InlineKeyboardButton("📜 Git Log", callback_data="cmd_git_log")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")],
    ])


def _back_kb(target="menu_main"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=target)]
    ])


def _run_cmd(cmd_list, timeout=10):
    try:
        result = subprocess.run(
            cmd_list, cwd="/public",
            capture_output=True, text=True, timeout=timeout,
        )
        return (result.stdout or result.stderr or "(no output)")[:3500]
    except subprocess.TimeoutExpired:
        return "⏱️ timeout"
    except Exception as e:
        return f"❌ {type(e).__name__}: {str(e)[:200]}"


async def cmd_panel(update, context):
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return
    await update.message.reply_text(
        "🤖 *NovaMind Control Panel*\n\nاختر:",
        parse_mode="Markdown",
        reply_markup=_main_menu_kb(),
    )


async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update):
        await query.edit_message_text("❌ غير مصرح.")
        return
    data = query.data

    if data == "menu_aider":


        try:


            from hive.tools.aider_bridge import is_available, current_model


            avail = is_available()


            model = current_model() if avail else "—"


        except Exception:


            avail = False


            model = "—"


        status = "✅ مثبت" if avail else "❌ غير مثبت"


        await query.edit_message_text(


            f"🛠️ *Aider — تعديل برمجي*\n\n"


            f"الحالة: {status}\n"


            f"الموديل: `{model}`\n\n"


            f"*الاستخدام:*\n"


            f"`/aider <file> <task>`\n\n"


            f"*أمثلة:*\n"


            f"`/aider core/llm_router.py راجع معالجة الأخطاء`",


            parse_mode="Markdown",


            reply_markup=_back_kb(),


        )


        return



    if data == "menu_main":
        await query.edit_message_text("🤖 *NovaMind Control Panel*\n\nاختر:",
            parse_mode="Markdown", reply_markup=_main_menu_kb())
        return

    if data == "menu_status":
        await query.edit_message_text("📊 *حالة النظام*",
            parse_mode="Markdown", reply_markup=_status_menu_kb())
        return

    if data == "menu_costs":
        await cmd_costs(update, context)
        return
    if data == "menu_evals":
        await cmd_evals(update, context)
        return
    if data == "menu_providers_v2":
        await cmd_providers_v2(update, context)
        return
    if data == "menu_memory":
        await cmd_memory(update, context)
        return
    if data == "menu_recall":
        await update.message.reply_text(
            "🔍 أرسل: `/recall <نص البحث>`", parse_mode="Markdown")
        return
    if data == "menu_tools":
        await cmd_tools(update, context)
        return
    if data == "menu_note":
        await update.message.reply_text(
            "📝 أرسل: `/note <نص>`", parse_mode="Markdown")
        return
    if data == "menu_halluc":
        await cmd_halluc(update, context)
        return
    if data == "menu_agents":
        try:
            from hive.runtime.adapter import AdapterRegistry
            reg = AdapterRegistry()
            agents = reg.list_agents()
            text = f"🤖 *الوكلاء* ({len(agents)})\n\n"
            text += "\n".join(f"• `{a}`" for a in agents[:25])
            if len(agents) > 25:
                text += f"\n\n... +{len(agents)-25} أكثر"
            await query.edit_message_text(text, parse_mode="Markdown",
                reply_markup=_back_kb())
        except Exception as e:
            await query.edit_message_text(f"❌ {e}", reply_markup=_back_kb())
        return

    if data == "menu_reports":
        try:
            from hive.core.store import summary
            m = summary()
            text = (f"📈 *التقارير*\n\n"
                    f"• المهام: {m.get('tasks', 0)}\n"
                    f"• الاكتشافات: {m.get('findings', 0)}\n"
                    f"• الأحداث: {m.get('events', 0)}\n")
            await query.edit_message_text(text, parse_mode="Markdown",
                reply_markup=_back_kb())
        except Exception as e:
            await query.edit_message_text(f"❌ {e}", reply_markup=_back_kb())
        return

    if data == "menu_providers":
        try:
            from novamind.core.llm_router import LLMRouter
            r = LLMRouter()
            text = f"🌐 *المزودون:* {len(r.providers)}\n\n"
            text += "\n".join(f"• `{p.name}`" for p in r.providers[:15])
            if len(r.providers) > 15:
                text += f"\n\n... +{len(r.providers)-15} أكثر"
            await query.edit_message_text(text, parse_mode="Markdown",
                reply_markup=_back_kb())
        except Exception as e:
            await query.edit_message_text(f"❌ {e}", reply_markup=_back_kb())
        return

    if data == "menu_keys":
        keys = ["GEMINI_API_KEY", "GITHUB_TOKEN",
                "TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_ID"]
        text = "🔐 *المفاتيح الحرجة:*\n\n"
        for k in keys:
            v = _os.getenv(k, "")
            text += f"• `{k}`: {'✅' if v else '❌'}\n"
        await query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=_back_kb())
        return

    if data == "cmd_df":
        out = _run_cmd(["df", "-h", "/"])
        await query.edit_message_text(f"💾 *القرص*\n\n```\n{out}\n```",
            parse_mode="Markdown", reply_markup=_back_kb("menu_status"))
        return

    if data == "cmd_free":
        out = _run_cmd(["free", "-h"])
        await query.edit_message_text(f"🧠 *الذاكرة*\n\n```\n{out}\n```",
            parse_mode="Markdown", reply_markup=_back_kb("menu_status"))
        return

    if data == "cmd_ps":
        out = _run_cmd(["ps", "aux"])
        lines = out.split("\n")
        if len(lines) > 15:
            out = "\n".join(lines[:15]) + f"\n... +{len(lines)-15}"
        await query.edit_message_text(f"⚡ *العمليات*\n\n```\n{out}\n```",
            parse_mode="Markdown", reply_markup=_back_kb("menu_status"))
        return

    if data == "cmd_uptime":
        out = _run_cmd(["uptime"])
        await query.edit_message_text(f"⏱️ *وقت التشغيل*\n\n`{out}`",
            parse_mode="Markdown", reply_markup=_back_kb("menu_status"))
        return

    if data == "cmd_git_status":
        out = _run_cmd(["git", "status", "--short"]) or "✅ لا تغييرات"
        await query.edit_message_text(f"📝 *Git Status*\n\n```\n{out}\n```",
            parse_mode="Markdown", reply_markup=_back_kb("menu_status"))
        return

    if data == "cmd_git_log":
        out = _run_cmd(["git", "log", "--oneline", "-5"])
        await query.edit_message_text(f"📜 *آخر commits*\n\n```\n{out}\n```",
            parse_mode="Markdown", reply_markup=_back_kb("menu_status"))
        return


# __UI_END__




async def cmd_aider(update, context):
    """تعديل برمجي مباشر عبر Aider."""
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "🛠️ *Aider — الاستخدام*\n\n"
            "`/aider <file> <task>`\n\n"
            "*أمثلة:*\n"
            "`/aider core/llm_router.py راجع معالجة الأخطاء`\n"
            "`/aider hive/core/nadj.py أضف تعليقات`",
            parse_mode="Markdown",
        )
        return

    file_path = args[0]
    task = " ".join(args[1:])

    try:
        from hive.tools.aider_bridge import is_available, run_aider_task, current_model
    except Exception as e:
        await update.message.reply_text(f"❌ تعذر تحميل Aider: {e}")
        return

    if not is_available():
        await update.message.reply_text(
            "❌ Aider غير مثبت.\n\nثبّته عبر: `pip install aider-chat`",
            parse_mode="Markdown",
        )
        return

    await update.message.chat.send_action("typing")
    await update.message.reply_text(
        f"🛠️ *Aider يعمل...*\n\n"
        f"📁 `{file_path}`\n"
        f"📝 {task[:200]}\n"
        f"🤖 `{current_model()}`",
        parse_mode="Markdown",
    )

    result = run_aider_task(
        files=[file_path],
        instruction=task,
        workdir="/public",
        timeout=240,
    )

    if result.get("success") and result.get("applied"):
        out = result.get("stdout", "")[-2500:]
        await update.message.reply_text(
            f"✅ *تم التعديل*\n\n```\n{out}\n```",
            parse_mode="Markdown",
        )
    else:
        err = result.get("error") or result.get("stderr") or result.get("stdout", "")[-1500:] or "unknown"
        await update.message.reply_text(
            f"❌ *لم يُطبَّق*\n\n```\n{err[:2000]}\n```",
            parse_mode="Markdown",
        )




# ═══════════════════════════════════════════════════════════
# ─── System Generator Command ───────────────────────────────




async def cmd_factory(update, context):
    """ينفّذ pipeline كامل من spec.

    /factory <pipeline_id> <task>
    /factory code_review def add(a,b): return a+b
    /factory list
    """
    import os

    admin_id = os.getenv("TELEGRAM_ADMIN_ID", "0")
    user_id = update.effective_user.id if update.effective_user else 0
    try:
        allowed = [int(admin_id)] if admin_id and admin_id != "0" else []
    except (ValueError, TypeError):
        allowed = []

    if user_id not in allowed:
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return

    args = context.args or []

    # بلا args → قائمة
    if not args or args[0] == "list":
        from hive.factory.pipeline import list_pipelines
        lines = ["🏭 *Factory — Pipelines المتاحة*", ""]
        for p in list_pipelines():
            lines.append(f"  • `{p['id']}`")
            lines.append(f"    _{p['description']}_")
        lines.append("")
        lines.append("*الاستخدام:*")
        lines.append("`/factory <pipeline_id> <task>`")
        lines.append("مثال:")
        lines.append("`/factory code_review def add(a,b): return a+b`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    pipeline_id = args[0]
    task = " ".join(args[1:]).strip()
    if not task:
        await update.message.reply_text("❌ المهمة مطلوبة.")
        return

    progress_msg = await update.message.reply_text(
        f"⏳ *Pipeline:* `{pipeline_id}`\n{task[:100]}...",
        parse_mode="Markdown",
    )

    from hive.factory.pipeline import run_pipeline
    try:
        result = await run_pipeline(pipeline_id, task)
    except Exception as e:
        await progress_msg.edit_text(f"❌ {type(e).__name__}: {str(e)[:300]}")
        return

    status = result.get("status", "unknown")
    emoji = {"done": "✅", "partial": "⚠️", "failed": "❌"}.get(status, "❓")

    lines = [
        f"{emoji} *Pipeline: {pipeline_id}*",
        f"الحالة: {status}",
        f"المراحل: {result.get('total_stages', 0)}",
        f"فشل: {result.get('failed_stages', 0)}",
        f"المدة: {result.get('duration_ms', 0)}ms",
    ]

    summary = result.get("summary", {})
    if summary:
        lines.append("")
        lines.append(f"📊 Tokens: {summary.get('total_tokens', 0)}")
        lines.append(f"✅ نجح: {summary.get('stages_passed', 0)}")
        lines.append(f"❌ فشل: {summary.get('stages_failed', 0)}")

    history = result.get("history", [])
    if history:
        lines.append("")
        lines.append("*التفاصيل:*")
        for h in history[:10]:
            mark = "✅" if h.get("success") else "❌"
            lines.append(f"  {mark} {h.get('agent', '?')} ({h.get('duration_ms', 0)}ms)")

    text = "\n".join(lines)

    if len(text) <= 3800:
        try:
            await progress_msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            await progress_msg.edit_text(text.replace("*", "").replace("`", ""))
    else:
        try:
            await progress_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(text[:3800], parse_mode="Markdown")


async def cmd_gen_system(update, context):
    """/gen_system <name> <json_spec>

    مثال:
      /gen_system todo_api {"entities":[{"name":"Task","fields":[{"name":"id","type":"int","primary":true},{"name":"title","type":"str"}]}]}
    """
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return

    args = context.args or []
    if len(args) < 2:
        help_text = (
            "📖 *الاستخدام:*\n"
            "`/gen_system <name> <json_spec>`\n\n"
            "*مثال:*\n"
            "`/gen_system todo_api {\"entities\":[{\"name\":\"Task\",\"fields\":[{\"name\":\"id\",\"type\":\"int\",\"primary\":true},{\"name\":\"title\",\"type\":\"str\"}]}]}`"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")
        return

    name = args[0].strip()
    raw_spec = " ".join(args[1:]).strip()

    import json
    try:
        spec = json.loads(raw_spec)
    except json.JSONDecodeError as e:
        await update.message.reply_text(
            f"❌ JSON غير صالح:\n`{str(e)[:200]}`",
            parse_mode="Markdown",
        )
        return

    spec.setdefault("name", name)

    await update.message.reply_text(f"⏳ جاري توليد `{name}`...", parse_mode="Markdown")

    try:
        from hive.generators.framework import generate_system, format_result
    except Exception as e:
        await update.message.reply_text(f"❌ فشل تحميل framework: {type(e).__name__}: {e}")
        return

    from pathlib import Path as _Path
    output_dir = _Path("/public/generated") / name

    try:
        result = generate_system(
            spec=spec,
            output_dir=output_dir,
            blueprint="api_backend",
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ خطأ غير متوقع: {type(e).__name__}: {str(e)[:300]}"
        )
        return

    text = format_result(result)
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(text.replace("*", "").replace("`", ""))


#  Agent Federation Commands
# ═══════════════════════════════════════════════════════════


async def cmd_agents_fed(update, context):
    """عرض 29 وكيل في federation."""
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return
    try:
        from hive.core.agents_registry import list_agents, get_agents_stats
        agents = list_agents()
        stats = {s["id"]: s for s in get_agents_stats()}

        lines = [f"🤖 *Agent Federation — {len(agents)} وكيل*\n"]
        by_spec = {}
        for a in agents:
            by_spec.setdefault(a["specialty"], []).append(a["name"])

        for spec in sorted(by_spec.keys()):
            names = by_spec[spec]
            lines.append(f"*{spec}* ({len(names)})")
            for n in names:
                tools = len(stats.get(n, {}).get("tool_calls", 0))
                lines.append(f"  • `{n}`  (calls: {tools})")
            lines.append("")

        msg = "\n".join(lines)[:3900]
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {type(e).__name__}: {str(e)[:200]}")


async def cmd_pipelines(update, context):
    """عرض 5 pipelines."""
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return
    try:
        from hive.orchestration.pipelines import list_pipelines, runs_stats
        pipelines = list_pipelines()
        stats = runs_stats()

        lines = ["🧭 *Pipelines*\n"]
        for p in pipelines:
            lines.append(
                f"• `{p['id']}` — {p['name']}\n"
                f"  stages: {p['stages']}, agents: {p['total_agents']}\n"
                f"  {p['description']}"
            )
            lines.append("")

        lines.append(f"📊 *Runs:* total={stats['total']}, done={stats['done']}, failed={stats['failed']}")
        msg = "\n".join(lines)[:3900]
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {type(e).__name__}: {str(e)[:200]}")


async def cmd_run_pipeline(update, context):
    """تشغيل pipeline: /run_pipeline <id> <description>"""
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "🧭 *الاستخدام:*\n"
            "`/run_pipeline <id> <description>`\n\n"
            "*مثال:*\n"
            "`/run_pipeline bug_fix أصلح خطأ في login`\n\n"
            "*Pipelines المتاحة:*\n"
            "• code_creation\n"
            "• code_review\n"
            "• bug_fix\n"
            "• refactor\n"
            "• deploy",
            parse_mode="Markdown",
        )
        return

    pipeline_id = args[0]
    description = " ".join(args[1:])
    task_id = f"tg-{update.effective_user.id}-{int(__import__('time').time())}"

    await update.message.reply_text(
        f"🧭 *Pipeline يبدأ...*\n\n"
        f"• ID: `{pipeline_id}`\n"
        f"• Task: `{task_id}`\n"
        f"• الوصف: {description[:200]}",
        parse_mode="Markdown",
    )

    try:
        from hive.orchestration.pipeline_runner import run_pipeline
        from hive.gates.quality_gate_v2 import evaluate_pipeline_result, format_gate_result
        from hive.self.evaluator import evaluate_pipeline_run

        result = run_pipeline(
            pipeline_id=pipeline_id,
            task_id=task_id,
            task_description=description,
            dry_run=False,
        )

        # قياس
        try:
            evaluate_pipeline_run(result)
        except Exception:
            pass

        # بوابة الجودة
        gate_result = evaluate_pipeline_result(pipeline_id, result)

        msg = (
            f"✅ *Pipeline انتهى*\n\n"
            f"• Run ID: `{result['run_id']}`\n"
            f"• Status: `{result['status']}`\n"
            f"• Duration: {result['total_duration_ms']}ms\n"
            f"• Stages: {len(result['stages'])}\n\n"
        )
        msg += format_gate_result(gate_result)
        await update.message.reply_text(msg[:3900], parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ {type(e).__name__}: {str(e)[:300]}")


async def cmd_costs(update, context):
    """ملخص التكاليف."""
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return
    try:
        from hive.self.costs import format_summary
        await update.message.reply_text(format_summary()[:3900], parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {type(e).__name__}: {str(e)[:200]}")


async def cmd_evaluator(update, context):
    """ملخص التقييمات."""
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return
    try:
        from hive.self.evaluator import format_summary
        await update.message.reply_text(format_summary()[:3900], parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {type(e).__name__}: {str(e)[:200]}")





# ═══════════════════════════════════════════════════════════
#  Git Commands (Admin only)
# ═══════════════════════════════════════════════════════════

async def cmd_git(update, context):
    """الأمر الموحد: /git <status|log|pull|push|backup|branches|diff>"""
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return
    if not context.args:
        await update.message.reply_text(
            "📌 *أوامر Git*\n\n"
            "`/git status` — الحالة\n"
            "`/git log [N]` — آخر N commits\n"
            "`/git pull` — سحب التحديثات\n"
            "`/git push <msg>` — commit + push\n"
            "`/git backup` — نسخة احتياطية\n"
            "`/git branches` — الفروع\n"
            "`/git diff` — التغييرات",
            parse_mode="Markdown",
        )
        return
    sub = context.args[0].lower()
    args = context.args[1:]
    try:
        if sub == "status":
            out = _gc.git_status()
        elif sub == "log":
            n = int(args[0]) if args and args[0].isdigit() else 5
            out = _gc.git_log(n)
        elif sub == "pull":
            await update.message.reply_text("⏳ جاري السحب...")
            out = _gc.git_pull()
        elif sub == "push":
            msg = " ".join(args) or f"auto: {datetime.now().isoformat(timespec='seconds')}"
            await update.message.reply_text("⏳ جاري commit + push...")
            out = _gc.git_sync(msg)
        elif sub == "backup":
            await update.message.reply_text("⏳ جاري النسخ الاحتياطي...")
            out = _gc.git_backup()
        elif sub == "branches":
            out = _gc.git_branches()
        elif sub == "diff":
            out = _gc.git_diff_stat()
        else:
            out = f"❌ أمر غير معروف: `{sub}`"
        await update.message.reply_text(out[:4000], parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {type(e).__name__}: {str(e)[:300]}")


async def cmd_agents_list(update, context):
    """قائمة الوكلاء."""
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return
    agents = _ar.list_agents()
    lines = [f"`{a}`" for a in agents[:30]]
    text = f"🤖 *الوكلاء ({len(agents)}):*\n\n" + "\n".join(lines)
    if len(agents) > 30:
        text += f"\n\n... و {len(agents) - 30} آخر"
    await update.message.reply_text(text[:4000], parse_mode="Markdown")


async def cmd_agents_run(update, context):
    """تشغيل وكيل: /agents_run <path>"""
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return
    if not context.args:
        await update.message.reply_text("📌 الاستخدام: `/agents_run path/to/script.py`", parse_mode="Markdown")
        return
    path = context.args[0]
    await update.message.reply_text(f"⏳ جاري تشغيل `{path}`...", parse_mode="Markdown")
    try:
        out = _ar.run_agent(path)
        await update.message.reply_text(out[:4000], parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {type(e).__name__}: {str(e)[:300]}")


async def cmd_agents_smoke(update, context):
    """اختبارات smoke."""
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return
    await update.message.reply_text("⏳ جاري تشغيل اختبارات smoke...")
    try:
        out = _ar.run_tests_smoke()
        await update.message.reply_text(out[:4000], parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {type(e).__name__}: {str(e)[:300]}")


async def cmd_agents_logs(update, context):
    """آخر logs."""
    if not _is_admin(update):
        await update.message.reply_text("❌ هذا الأمر للمسؤول فقط.")
        return
    out = _ar.get_agent_logs()
    await update.message.reply_text(out[:4000], parse_mode="Markdown")





async def cmd_evals(update, context):
    """عرض التقييمات من eval_tracker."""
    if not _HAS_EVALS:
        await update.message.reply_text("⚠️ eval_tracker غير متاح")
        return
    try:
        data = _get_evals(limit=20)
        lines = ["📊 **التقييمات (آخر 20):**\n"]
        if isinstance(data, list):
            for row in data[:20]:
                lines.append(f"  • {row}")
        else:
            lines.append(f"  {data}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def cmd_providers_v2(update, context):
    """عرض المزودين المتاحين من registry."""
    if not _HAS_PROVIDERS:
        await update.message.reply_text("⚠️ ProviderRegistry غير متاح")
        return
    try:
        reg = _get_provider_registry()
        avail = reg.available()
        lines = [f"🌐 **المزودون المتاحون ({len(avail)}):**\n"]
        for name in avail:
            lines.append(f"  ✅ {name}")
        if not avail:
            lines.append("  ❌ لا مزود متاح — تحقق من المفاتيح في .env")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def cmd_halluc(update, context):
    """اختبار كاشف الهلوسة."""
    if not _HAS_HALLUC:
        await update.message.reply_text("⚠️ HallucinationDetector غير متاح")
        return
    try:
        detector = _HallucinationDetector()
        sample = "As an AI language model, I cannot access that."
        result = detector.check(sample, "test")
        msg = f"🛡️ **كاشف الهلوسة — تجربة:**\n\nالنص: `{sample[:60]}`\n\nالنتيجة: `{result}`"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")




# ═══════════════════════════════════════════════════════
#  Handlers الذاكرة الدلالية
# ═══════════════════════════════════════════════════════

async def cmd_memory(update, context):
    """إحصائيات الذاكرة."""
    if not _HAS_MEMORY:
        await update.message.reply_text("⚠️ Memory غير متاح")
        return
    try:
        mem = _get_memory()
        s = mem.stats()
        lines = ["🧠 **الذاكرة الدلالية**\n"]
        lines.append(f"  📦 إجمالي النصوص: `{s['total']}`")
        lines.append(f"  🗂️ Namespaces: `{len(s['namespaces'])}`")
        for ns in s['namespaces'][:10]:
            lines.append(f"    • {ns}")
        lines.append("\n**الاستخدام:**")
        lines.append("  `/recall <نص>` — بحث دلالي")
        lines.append("  `/note <نص>` — حفظ ملاحظة")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def cmd_recall(update, context):
    """بحث دلالي."""
    if not _HAS_MEMORY:
        await update.message.reply_text("⚠️ Memory غير متاح")
        return
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("⚠️ استخدم: `/recall <نص البحث>`", parse_mode="Markdown")
        return
    try:
        mem = _get_memory()
        results = await mem.recall(query, namespace="telegram", top_k=5)
        if not results:
            await update.message.reply_text("📭 لا نتائج")
            return
        lines = [f"🔍 **نتائج البحث عن:** `{query[:60]}`\n"]
        for i, r in enumerate(results, 1):
            score = r["score"]
            text = r["text"][:200]
            lines.append(f"{i}. `score={score:.3f}`")
            lines.append(f"   {text}")
            lines.append("")
        await _send_long(update.message, "\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def cmd_note(update, context):
    """حفظ ملاحظة في الذاكرة."""
    if not _HAS_MEMORY:
        await update.message.reply_text("⚠️ Memory غير متاح")
        return
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("⚠️ استخدم: `/note <نص>`", parse_mode="Markdown")
        return
    try:
        mem = _get_memory()
        rid = await mem.remember(text, namespace="telegram", meta={"source": "telegram"})
        if rid > 0:
            await update.message.reply_text(f"✅ حُفظ (id={rid})")
        else:
            await update.message.reply_text("❌ فشل الحفظ — تحقق من logging")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")




# ═══════════════════════════════════════════════════════
#  ToolAgent — الأدوات الذكية
# ═══════════════════════════════════════════════════════

async def cmd_tools(update, context):
    """عرض الأدوات المتاحة."""
    if not _HAS_TOOLS:
        await update.message.reply_text("⚠️ الأدوات غير متاحة")
        return
    try:
        from hive.tools import get_registry
        reg = get_registry()
        stats = reg.stats()
        lines = [f"🛠️ **الأدوات المتاحة ({stats['total']})**\n"]
        for cat in stats["categories"]:
            tools = reg.list_tools(category=cat)
            lines.append(f"\n**{cat}:**")
            for t in tools:
                danger = "⚠️" if t.dangerous else "•"
                lines.append(f"  {danger} `{t.name}`")
        lines.append("\n💡 **الاستخدام:**")
        lines.append("أرسل أي سؤال عادي — البوت سيقرر متى يستخدم الأدوات.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def cmd_agent(update, context):
    """اختبار ToolAgent بأمر."""
    if not _HAS_TOOLS:
        await update.message.reply_text("⚠️ الأدوات غير متاحة")
        return
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("⚠️ استخدم: `/agent <سؤال>`", parse_mode="Markdown")
        return
    msg = await update.message.reply_text("🤔 أفكر...")
    try:
        agent = _get_tool_agent()
        r = await agent.chat(text)
        if r.get("ok"):
            reply = r.get("reply", "(لا رد)")
            tools_used = r.get("tool_calls", [])
            header = ""
            if tools_used:
                header = f"🛠️ استخدمت {len(tools_used)} أداة:\n"
                for tc in tools_used[:3]:
                    header += f"  • `{tc['name']}`\n"
                header += "\n"
            full = header + reply
            await _send_long(msg, full)
        else:
            await msg.edit_text(f"❌ {r.get('error', '?')[:400]}")
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {e}")


async def cmd_agents_message(update, context):
    """معالج الرسائل العادية — يستخدم ToolAgent."""
    if not _HAS_TOOLS:
        return
    text = update.message.text
    if not text or text.startswith("/"):
        return
    # فقط إذا الرسالة طويلة أو تبدو كسؤال
    if len(text) < 5:
        return
    # مؤشر تفكير
    thinking = await update.message.reply_text("🤔")
    try:
        agent = _get_tool_agent()
        r = await agent.chat(text)
        if r.get("ok"):
            reply = r.get("reply", "(لا رد)")
            tools_used = r.get("tool_calls", [])
            header = ""
            if tools_used:
                header = f"🛠️ {len(tools_used)} أداة: "
                header += ", ".join(f"`{tc['name']}`" for tc in tools_used[:3]) + "\n\n"
            await thinking.edit_text((header + reply)[:4000])
        else:
            # لا نُزعج المستخدم إذا فشل — نتركه صامتاً
            await thinking.delete()
    except Exception as e:
        await thinking.delete()


def main():
    print("Starting Unified Bot...")
    app = Application.builder().token(token()).build()

    # General
    app.add_handler(CommandHandler("agents", cmd_agents_fed))
    app.add_handler(CommandHandler("pipelines", cmd_pipelines))
    app.add_handler(CommandHandler("run_pipeline", cmd_run_pipeline))
    app.add_handler(CommandHandler("evaluator", cmd_evaluator))
    app.add_handler(CommandHandler("gen_system", cmd_gen_system))
    app.add_handler(CommandHandler("factory", cmd_factory))
    app.add_handler(CommandHandler("aider", cmd_aider))
    app.add_handler(CommandHandler("costs", cmd_costs))
    app.add_handler(CommandHandler("evals", cmd_evals))
    app.add_handler(CommandHandler("providers_v2", cmd_providers_v2))
    app.add_handler(CommandHandler("halluc", cmd_halluc))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("recall", cmd_recall))
    app.add_handler(CommandHandler("note", cmd_note))
    app.add_handler(CommandHandler("tools", cmd_tools))
    app.add_handler(CommandHandler("agent", cmd_agent))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler('panel', cmd_panel))
    app.add_handler(CommandHandler('menu', cmd_panel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler('panel', cmd_panel))
    app.add_handler(CommandHandler('menu', cmd_panel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("help", cmd_help))

    # HiveLoop
    app.add_handler(CommandHandler("hive_status", cmd_hive_status))
    app.add_handler(CommandHandler("hive_list", cmd_hive_list))
    app.add_handler(CommandHandler("hive_recent", cmd_hive_recent))
    app.add_handler(CommandHandler("hive_stats", cmd_hive_stats))
    app.add_handler(CommandHandler("hive_morning", cmd_hive_morning))
    app.add_handler(CommandHandler("hive_run", cmd_hive_run))
    app.add_handler(CommandHandler("hive_parallel", cmd_hive_parallel))
    app.add_handler(CommandHandler("hive_workflow", cmd_hive_workflow))

    # NovaMind
    app.add_handler(CommandHandler("nm_status", cmd_nm_status))
    app.add_handler(CommandHandler("nm_agents", cmd_nm_agents))
    app.add_handler(CommandHandler("nm_leaderboard", cmd_nm_leaderboard))
    app.add_handler(CommandHandler("nm_report", cmd_nm_report))
    app.add_handler(CommandHandler("nm_evaluate", cmd_nm_evaluate))
    app.add_handler(CommandHandler("nm_evolve", cmd_nm_evolve))
    app.add_handler(CommandHandler("nm_schedule", cmd_nm_schedule))
    app.add_handler(CommandHandler("nm_mission", cmd_nm_mission))
    app.add_handler(CommandHandler("nm_recruit", cmd_nm_recruit))
    app.add_handler(CommandHandler("nm_develop", cmd_nm_develop))
    app.add_handler(CommandHandler("nm_upgrade", cmd_nm_upgrade))
    app.add_handler(CommandHandler("nm_retrain", cmd_nm_retrain))
    app.add_handler(CommandHandler("nm_purge", cmd_nm_purge))
    app.add_handler(CommandHandler("nm_clone", cmd_nm_clone))
    app.add_handler(CommandHandler("nm_insights", cmd_nm_insights))
    app.add_handler(CommandHandler("nm_inject_vaccine", cmd_nm_inject_vaccine))

    # Fingerprint
    app.add_handler(CommandHandler("shell", cmd_shell))
    app.add_handler(CommandHandler("verify", cmd_verify))
    app.add_handler(CommandHandler("trust", cmd_trust))
    app.add_handler(CommandHandler("svc", cmd_svc))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("generated", cmd_generated))

    # Git & Agents (admin only)
    app.add_handler(CommandHandler("git", cmd_git))
    app.add_handler(CommandHandler("agents_list", cmd_agents_list))
    app.add_handler(CommandHandler("agents_run", cmd_agents_run))
    app.add_handler(CommandHandler("agents_smoke", cmd_agents_smoke))
    app.add_handler(CommandHandler("agents_logs", cmd_agents_logs))

    # Fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_echo))

    print("Running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
