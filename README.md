<p align="center">
  <img src=".github/assets/banner.svg" alt="nexus-core" width="100%">
</p>

# nexus-core — النظام الجامع للوكلاء

> **نظام وكلاء ذكاء اصطناعي موحّد يعمل على جهازك** — ذاكرة طويلة المدى، تعلّم مستمر، أمن offline، ومجلس قرارات حيّ. قابل للتدقيق سطراً بسطر، لا صندوق أسود.

**Unified AI Agent System: Memory + Learning + Security + 20 Agents — self-hosted, auditable, stdlib-only core.**

[![CI](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/ci.yml/badge.svg)](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/ci.yml)
[![Tests](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/test.yml/badge.svg)](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/test.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/tibatechapp-ship-it/nexus-core/main/.github/badges/coverage.json)](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Release](https://img.shields.io/github/v/release/tibatechapp-ship-it/nexus-core)](https://github.com/tibatechapp-ship-it/nexus-core/releases)

---

## 🎯 ما هذا؟ ولمن هذا؟

- **ما هو**: منصة وكلاء AI ذاتية الاستضافة — 20 وكيل مدمج، إشراف (supervisor)، ذاكرة دائمة من 4 متاجر SQLite، تعلّم مستمر من التجربة، مجلس مداولات حيّ، أدوات MCP أصلية، وماسح أمني يعمل بلا شبكة. النواة **بايثون قياسي خالص** — تعمل حتى على هاتف، بلا تثبيتات.
- **لمن**: مهندسو وباحثو AI الذين يبنون وكلاء مستقلين ويريدون **وقت تشغيل يدققونه بأنفسهم** على أجهزتهم — لا خدمة مستضافة تُخفي قراراتها.
- **الحالة بصدق**: جاهزية بنية تحتية عالية اليوم — ومع أسبوعي 1-2 من خارطة المنتَجة أصبح يوجد: لوحة قراءة-فقط (`/dashboard`) وسجل أثر معياري (`runs/trace.jsonl`). ما تبقى: benchmarks منشورة، OpenAPI + مصفوفة صلاحيات، وdemo بنقرة — وكلها في [خارطة المنتج](https://github.com/tibatechapp-ship-it/vixona-github-profile/blob/main/docs/productization-plan.md).

## ✅ يعمل اليوم — بالدليل (2026-10-31)

| القدرة | الدليل القابل للتحقق |
|---|---|
| كتلة اختبارات ضخمة | **3,789 حالة اختبار مجمّعة في 212 ملفاً** (`pytest --collect-only`) + طبقة `tests/novamind` الاختيارية |
| CI مزدوج أخضر | [CI](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/ci.yml) + [Tests](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/test.yml) على main |
| بوابة جودة واحدة | `make check` = ruff + mypy + فحص التعليقات النمطية + اختبارات بتغطية ~99% |
| لوحة قراءة-فقت | `/dashboard` + `/api/dashboard` — وكلاء نشطون، مهام جارية، آخر قرارات المجلس (**8 اختبارات httpx**) |
| سجل أثر معياري | كل تشغيل وكيل/مجلس يكتب سطر JSON (`ts/agent/tool/duration_ms/outcome`) في `runs/trace.jsonl` + `/api/trace/recent` (**20 اختبار انحدار**) |
| حرس أحمر أمني | `tests/adversarial` — **92 متجه هجوم في 8 فئات** + قيد سلسلة توريد حي يفشل عند أي استيراد غير معلن |
| حوكمة موثقة | [SCOPE](SCOPE.md) · [VISION_2026](VISION_2026.md) · [ADVERSARIAL](ADVERSARIAL.md) · [LESSONS](LESSONS.md) · [CHANGELOG](CHANGELOG.md) |
| نشر | Docker + docker-compose · إصدارات مُوسومة · CITATION.cff |

## 🚀 البدء في 60 ثانية

```bash
git clone https://github.com/tibatechapp-ship-it/nexus-core.git
cd nexus-core
make check        # البوابة الخضراء كاملة: ruff + mypy + annotations + 3,789 اختبار
```

```bash
# TUI لوكلاء العشرين (نواة stdlib — بلا أي تبعية)
python -c "from src.core.backend import EchoBackend; from src.tui.app import run_app; run_app(backend=EchoBackend())"

# مساعد تيليجرام / صوتي / ماسح أمني
python zyvo-telegram.py
python zyvo-voice.py
python -m src.security . --fail-on high
```

## 🗺️ المعمارية — مستودع واحد، طبقتان، كل الميزات

```
src/            الإطار (stdlib فقط، آمن للهاتف، مُختبر بالكامل)
  agents/       20 وكيل مدمج (core/planning/quality/ops)
  core/         أنواع، بروتوكول مزودات LLM، بث، سياق، صمود
  patterns/     Supervisor, Pipeline (قابل للاستئناف), Fanout, Delegation, Blackboard
  memory/       4 متاجر SQLite (episodic/semantic/procedural/emotional) + RAG
  learning/     جامع تجارب → دروس → ضد النسيان
  security/     ماسح أمني ثابت offline (8 وكلاء) + CLI
  tools/        تنفيذ أدوات قراءة فقط (حلقة ReAct، جذر محصور)
  tui/          واجهة Textual طرفية (شاشات، آثار أدوات، أمن)
  mcp/          خادم/عميل Model Context Protocol + جسر وكلاء (30 أداة)
  council/      محرك مجلس العمل (3 أعضاء) + توليد Craft
  novamind/     طبقة الخادم (extras اختياري `novamind`)
hyper_agent.py  Hyper-Agent 2.0 — وكيل برمجة ذاتي (BUG-1..9 مصممة من الولادة)
connectors/     مهايئات LLM BYOK (openai/anthropic/groq/ollama/deepseek/gemini)
hyper_app/      سطح API للوكيل الذاتي (POST /api/agent/start)
tests/          جناح الإطار (3,789+ حالة) + tests/adversarial (92 متجه) + tests/novamind/
main.py         خادم مجلس العمل (FastAPI) + console/index.html
zyvo-*.py       مساعدا تيليجرام والصوت المستقلان
docs/           توثيق الإطار + novamind
```

## 💬 خادم دردشة + واجهة ويب (v1.5)

طبقة FastAPI (`unified_agent.py`) تخدم واجهة بأسلوب ChatGPT + API JSON صغير — التاريخ محفوظ في SQLite خادمياً، مع «آلة زمن» لكل طلب.

```bash
python -m pip install -e ".[novamind]"
PYTHONPATH=src/novamind:src:. python unified_agent.py   # http://localhost:8000
```

- **Persistence** — `data/sessions.db` (sqlite3 قياسي، WAL) + ترحيل تلقائي من `localStorage`.
- **Time Machine** — كل طلب مُسجّل (رسالة، رد، وكيل، زمن، حالة، مخرج المخطط) تحت `/api/traces` مع إعادة تشغيل وتصدير JSON/Markdown.
- **API** — `/api/chat` (بث SSE)، `/api/conversations[...]`، `/api/traces[...]`، `/api/export/conversations`، `/api/db/stats`.

## ⚖️ مجلس العمل + Craft (v1.12) والمجلس الحيّ (v2.0)

ثلاثة أعضاء (Profiler/Analyst/Critic) يداومون سؤالاً بالعربية أو الإنجليزية ويعيدون حكماً + درجة ثقة + توصية، مبثوثة حياً عبر SSE. **Craft** (`POST /api/craft`) يحول وصفاً حراً إلى **كود عامل فعلياً**: مسارات محصورة، امتدادات مُدرجة بيضاء، وكل `.py` مولّد يمر عبر `py_compile` — الرد يحمل كتلة `proof` (لا نجاح صامت).

**المجلس الحيّ (v2.0)**: 5 أعضاء متخصصين يداومون 1–5 جولات بأسهم موقف تعلو أو تهبط حسب انسجامهم مع القرار النهائي:

- **Engine** — `src/novamind/council/council.py` + إجماع لكل جولة (token-Jaccard) وتوقف مبكر عند ≥ 0.8.
- **يعمل offline** — محاكاة محلية حتمية بلا مزود؛ فشل حي يقلب الجلسة offline لـ60 ثانية (شفاء ذاتي).
- **API** — `POST /api/council/stream` (SSE)، `POST /api/council/debate`، `GET|DELETE /api/council/sessions/{id}`.

## 🧬 جينوم الوكلاء (v2.0)

لكل وكيل جينوم دائم: شخصية، نسب (جيل/والد)، وأداء مدى الحياة (تشغيلات، نجاحات، زمن، انسجام مع الأحكام). الموقف يرتفع وينخفض عبر الجلسات — القوي يُرقّى، والضعيف يُوضع تحت المراقبة ويُعاد تدريبه.

- **Engine** — `src/novamind/genome/`: `scoring.py` نقي + مدير `Genome` فوق جدولي SQLite `agent_genome` و`genome_events`.
- **API** — `GET /api/genome` (ترتيب الوكلاء)، `PATCH /api/genome/{id}` (تعديل شخصية)، `POST /api/genome/{id}/reset` (إعادة تدريب)، `GET /api/genome/export`.

## 📱 PWA + offline (v2.0)

الواجهة تطبيق ويب تقدمي قابل للتثبيت (عربي RTL) يستمر بلا شبكة: service worker يحفظ الهيكل مسبقاً ولا يخزن `/api/*` أبداً (البث يبقى حياً)، ورسائل offline تصطف في IndexedDB وتُعاد تلقائياً عند رجوع الاتصال.

## 🤖 Hyper-Agent 2.0 — وكيل برمجة ذاتي (BYOK)

حلقة برمجة ذاتية القيادة: LLM يقترح فعل JSON واحداً كل دورة (`CODE`/`TEST`/`DONE`/`ERROR`)، يُنفذ في صندوق subprocess بحدود rlimits (يعمل حتى على Android)، و`verify_goal` يبوّب الخروج. كل دورة تُلحق بسجل JSONL قابل لإعادة التشغيل سطراً بسطر. أنماط الفشل التسعة (BUG-1..9) مصممة من الولادة — التاريخ يُستبدل لا يُلحق، وكشف التجمد ينهي التشغيل المتجمد، و`last_parse_error` يُطعم للنموذج ليصحح JSON.

- **`connectors/`** — BYOK خلف عقد واحد `{"ok": bool, "reply"|"error": str}` لستة مزودين، المفاتيح من متغيرات البيئة المعتادة.
- **Tests** — `tests/test_hyper_agent.py` + `tests/test_byok_integration.py` (41 اختباراً محكماً بلا شبكة). تغطية `hyper_agent.py` = 99%، `src/learning` = 100%.
- **أداء موثق** — قاطع دارات + تعدد مفاتيح (Ollama Cloud ×7، OpenRouter ×10) أنزل متوسط الاستجابة من 30–40 ثانية فشل مزود إلى **~2.3 ثانية** (v1.46)، وواجهة Split UI مفصولة CSS/JS (v1.47)، و4 اختبارات E2E للدردشة (v1.48).

```bash
# اختبارات الحلقة
PYTHONPATH=.:src python3 -m pytest tests/test_hyper_agent.py tests/test_byok_integration.py -q

# هدف واحد عبر API (يتطلب مفتاح مزود مُعداً)
curl -X POST http://127.0.0.1:8000/api/agent/start \
  -H 'Content-Type: application/json' \
  -d '{"goal": "write a fibonacci function with tests", "max_iterations": 5}'
```

## 📊 اللوحة وسجل الأثر — أسبوعا 1-2 من خارطة المنتَجة

```bash
# اللوحة (قراءة-فقت): الوكلاء النشطون + المهام الجارية + آخر قرارات المجلس + أحداث الأثر
python -m uvicorn src.web.app:app --port 8000
# ثم افتح http://127.0.0.1:8000/dashboard  (واجهة عربية بلا JS)

# سجل الأثر المعياري: كل تشغيل وكيل/مجلس = سطر JSON واحد
# بالحقول الإلزامية ts / agent / tool / duration_ms / outcome
make trace-tail
```

سطر أثر فعلي:

```json
{"ts": "2026-10-31T18:34:31.126+00:00", "agent": "code-reviewer", "tool": "run", "duration_ms": 0.021, "outcome": "ok"}
```

المسار قابل للتوجيه عبر `NEXUS_TRACE_PATH`، ويتدور تلقائياً عند 5 ميغابايت، وبلا محتوى مستخدم (لا PII بالتصميم). الفشل مُوثَّق كذلك: `outcome: "error"` مع **نوع** الاستثناء فقط.

## 🚧 الحدود الصادقة (لنتحدث بها كاملة)

- لا **benchmarks منشورة** قابلية للمقارنة الخارجية — الأداء المذكور أعلاه من جلسات فعلية لكنه غير مؤتمت القياس.
- لوحة `/dashboard` وسجل `runs/trace.jsonl` يغطيان طبقة `src/web` ووكلاء الـregistry؛ تتبع دردشة `unified_agent` (`/api/traces`) مستقل كما كان.
- طبقة novamind تحتاج extras اختيارياً ولا تدخل بوابات الإطار (تُختبر بجناحها في CI).

هذان أول أسبوعين من [خارطة المنتج](https://github.com/tibatechapp-ship-it/vixona-github-profile/blob/main/docs/productization-plan.md) والثالث قادم (benchmarks مؤتمتة) — بعدها يصبح أول 5 دقائق تجربة كاملة بلا قراءة توثيق.

## ✅ تحقق قبل الشحن (يجب أن يجتاز الكل)

```bash
make check
```

أو يدوياً:

```bash
ruff check .
mypy zyvo-telegram.py zyvo-voice.py src
python scripts/check_annotations.py        # كل دالة معلّمة الأنواع
python -m pytest --cov --cov-fail-under=95 --ignore=tests/novamind
```

جناح novamind يحتاج الـextras ويعمل في CI (يُتخطى تلقائياً عند غيابها).

## 🧭 المكان في المحفظة

nexus-core هو **الدرجة الأولى** في [محفظة TibaTech](https://github.com/tibatechapp-ship-it/vixona-github-profile) — انظر [بطاقة الأداء الكاملة](https://github.com/tibatechapp-ship-it/vixona-github-profile/blob/main/docs/scorecard.md) وخارطة المنتَجة لما تبقى.

## LICENSE

MIT — see [LICENSE](LICENSE).
