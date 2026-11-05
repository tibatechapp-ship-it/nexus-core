# قرار إقرار المراجعة الأمنية الساكنة — v1.58.0

> **المنهجية**: المراجعة الخارجية رصدت 9 نقاط ضد الالتزام `ed92aa9`. قبل أي
> إصلاح، فُحصت كل نقطة ضد الكود الفعلي سطرًا سطرًا (اعتمد الصحيح فقط). النتيجة:
> **9/9 مؤكدة** (7 كلية، 2 جزئية بفروق تنفيذ)، ومعها **قراران مضادان** موثقان
> أسفل الجدول. وفي جولة التحقق نفسها رُصدت نقطة **عاشرة** (ض10) لم تغطّها
> المراجعة — ظهرت بعد `ed92aa9` بدمج الماسح الآلي MIZAN — وأُقرّت وأُصلحت
> هنا أيضًا. كل إصلاح مقترن باختبار انحدار في
> `tests/test_security_hardening_v158.py` يذكر الثغرة ودفاعها.

## جدول الإقرار

| # | الادعاء | الحكم | الدليل (الكود عند ed92aa9) | الإصلاح المعتمد | اختبار الانحدار |
|---|---|---|---|---|---|
| ض1 | VFS يقرأ/يكتب خارج المشروع | **مؤكد** | `src/novamind/core/vfs.py`: `_check` يمنع قائمة بادئات فقط (`/etc,/proc,...`)؛ مسار مطلق كـ `/home/u/.ssh/id_rsa` يمرّ؛ الروابط الرمزية تُحل خارج الجذر دون رفض | احتواء صارم بعد `resolve()` في `_check` (يشمل read/write/delete/exists/append/list_dir)؛ الخروج ⇒ `FORBIDDEN_PATH` | `test_d1_vfs_rejects_absolute_path_outside_root`، `test_d1_vfs_rejects_symlink_escape`، `test_d1_vfs_sibling_prefix_root_is_not_confused` |
| ض2 | أدوات Shell/Python تنفّذ على الخادم بلا عزل | **مؤكد** | `src/novamind/tools/shell_tools.py`: القائمة تضم `python3 pip3 curl wget git rm chmod` بالاسم فقط؛ `RunPythonTool` ينفّذ كودًا محددًا بلا عزل | تعطيل افتراضي: التسجيل مشروط بـ `NEXUS_ENABLE_SHELL_TOOLS=1` قبل الاستيراد؛ حذف المفسّرات والشبكة والحذف/الصلاحيات من القائمة؛ `git` مقصور على 10 أوامر قراءة؛ توثيق أن العزل الحقيقي OS-level شرط للتفعيل | `test_d2_shell_tools_disabled_by_default`، `test_d2_shell_tools_register_only_with_explicit_opt_in`، `test_d2_interpreters_network_and_destructive_are_not_whitelisted`، `test_d2_git_is_restricted_to_read_only_subcommands` |
| ض3 | `grep` يتبع رابطًا رمزيًا خارج مساحة العمل | **مؤكد** | `src/tools/executor.py`: `_walk_text_files` يمرّ على `rglob("*")` دون فحص احتواء للمسار النهائي؛ `_resolve` يحمي وسيط المستخدم فقط | فحص احتواء لكل مرشح بعد `resolve()` داخل `_walk_text_files`؛ أي مرشح يهرب الجذر يُتخطى | `test_d3_grep_skips_symlink_pointing_outside` |
| ض4 | `_safe_target` بمقارنة نصية | **مؤكد** | `src/coder/sandbox.py`: `str(target).startswith(str(workdir.resolve()))` — جذر `/tmp/work` ومسار `/tmp/work-other/file` يمرّان | `target.is_relative_to(root)` بعد الحلّ | `test_d4_safe_target_rejects_sibling_prefix` + اختبار قائم `test_safe_target_rejects` |
| ض5 | التقاط المخرجات غير المقيّد وقتل الابن فقط | **مؤكد** | `run_cmd`: `communicate()` يلتقط كل شيء في الذاكرة ثم يقصّ؛ عند المهلة `proc.kill()` للابن المباشر فقط بينما الجلسة `start_new_session` قد تحمل أحفادًا | تصريف بخيوطين يتوقفان عن التراكم عند `MAX_OUTPUT_BYTES` (الفائض يُهدر ولا يُسد الأنبوب) + `truncated` في النتيجة؛ عند المهلة `os.killpg` لمجموعة الجلسة كاملة | `test_d5_run_cmd_caps_output_while_reading`، `test_d5_timeout_kills_the_whole_process_group` (يتحقق من موت الحفيد بمعرّفه) |
| ض6 | `edit` يُلحق بالإجراء المجهول يكتب فوق الملفات | **مؤكد** | `apply_plan`: فرع `else` يكتب `patch_hint`؛ `edit` يُلحق بنهاية الملف؛ أي إجراء غير معروف يعامل كتابةً | دلالات صريحة: `edit` = استبدال مقطع فريد (`find` مرة واحدة بالضبط ⇒ `patch_hint`)؛ `create` يرفض الكتابة فوق موجود؛ إجراء مجهول ⇒ خطأ مسجّل؛ `plan.validate` يشترط `find` على edit؛ موجه المحرك محدّث بالحقل الجديد | `test_d6_create_refuses_to_overwrite`، `test_d6_edit_replaces_unique_block`، `test_d6_edit_rejects_ambiguous_and_missing_find`، `test_d6_unknown_action_is_an_error_not_a_write`، `test_d6_validation_requires_find_on_edit`، `test_d6_plan_from_json_carries_find` |
| ض7 | Ruff لا يوقف CI | **مؤكد** | `ci.yml`: `ruff check ... \|\| true` — أخطاء lint تبقي الـ workflow أخضر | إزالة `\|\| true`؛ الشجرة نظيفة تحت `[tool.ruff]` (تحقق محليًا قبل التغيير) | `test_d7_ruff_is_a_hard_gate_in_ci` (يفحص نص الـ workflow + يشغّل ruff فعليًا) |
| ض8 | صلاحية كتابة واسعة + novamind غير حاجبة | **مؤكد جزئيًا** | `test.yml`: `contents: write` على مستوى الـ workflow بينما الوظيفة الوحيدة التي تكتب فعليًا هي `coverage-badge` (شارة + تقارير)؛ اختبارات novamind `continue-on-error` موثقة كتقارير | أقل امتياز: `contents: read` افتراضيًا للـ workflow و`contents: write` على وظيفة `coverage-badge` حصرًا. بند «اجعل novamind حاجبًا» **مرفوض** (قرار مضاد 1 أدناه) | `test_d8_test_workflow_is_least_privilege` |
| ض9 | واجهات الويب بلا حارس مصادقة | **مؤكد** | `src/web/app.py`: 9 نقاط نهاية متغيّرة (`/api/agent/run`, `/api/rag/add`, `/api/cache/clear`, `/api/metrics/clear`, `/api/council/*`, `/api/hybrid/run`, `/api/smart/run`, `/api/a2a/message`) بلا middleware؛ الحارس `AccessGuard` موجود في المستودع لكنه مركّب على البوابة الموحدة فقط | تركيب نفس `AccessGuard` (token ثابت الزمن + حدّ معدّل 120/60s + تدقيق + فشل مغلق لغير loopback) كـ HTTP middleware على التطبيق نفسه؛ القراءات تمر دائمًا | `test_d9_web_app_guard_requires_token_for_mutations`، `test_d9_web_app_guard_reads_token_from_env` |
| ض10 | خط أنابيب MIZAN قابل للاختراق بأي PR + تلوّث المستودع | **مؤكد (رصد ذاتي)** | `.github/workflows/mizan-scan.yml`: `pull_request_target` مع صلاحيات كتابة وأسرار المستودع بينما يُخرَج ويُنفَّذ كود الـ PR نفسه (`run_mizan.py`/`secret_remover.py`/`ai_fixer.py`) — أي PR يمكنه تسريب التوكن؛ و`git add .` ألزم `node_modules/` كاملة (+1200 ملف) و`package.json` وأشعة SARIF في git | تحويل المشغّل إلى `pull_request` (تُسلب صلاحيات الكتابة والأسرار عن PR الشوكة تلقائيًا)؛ استبدال `git add .` بمسارات صريحة تستثني مخرجات الماسح؛ حذف الملفات المتلوّثة من الشجرة (`node_modules/`, `package.json`, `package-lock.json`, `bandit.sarif`, `semgrep.sarif`, `test_mizan.txt`) وضمانة `.gitignore` | `test_d10_mizan_workflow_uses_pull_request_not_target`، `test_d10_mizan_autocommit_excludes_scanner_artifacts`، `test_d10_scanner_artifacts_are_gitignored`، `test_d10_scanner_artifacts_are_not_tracked` |

## القراران المضادان (ما رُفض من التقييم مع السبب)

### قرار مضاد 1 — «حوّل اختبارات novamind إلى بوابة ملزمة»
مرفوض لهذا الإصدار. الطبقة تعمل ببيئتها وبياناتها الخاصة وتُدار بقرار معماري
موثق منذ v1.44: تقارير غير حاجبة في CI (`continue-on-error` مع تسمية صريحة
«non-blocking report»). الاعتماد هنا: تقييد الصلاحيات (الأهم عمليًا)، وترك
قرار «التخطيط كبوابة» لمرحلة تثبيت بيئة novamind في CI كخطوة مستقلة — لا
تغيير صامت في العقد الحالي.

### قرار مضاد 2 — «اعزل التنفيذ بحاوية OS غير مميزة»
الصحيح مبدئيًا ولا توجد خلاف عليه، لكنه لا يُنفَّذ داخل المستودع: المنصة
مقيّدة بالهاتف (Termux) والنشر المستهدف ليس Kubernetes. المعتمد عمليًا:
- الأداتان **معطّلتان افتراضيًا** (بوابة تفعيل صريحة) — خيار التقييم الأول
  «عطّل هذه الأدوات».
- التوثيق يعلن أن قائمة الأوامر ليست حدًا أمنيًا وأن التفعيل في نشر غير موثوق
  يشترط عزل OS (حاوية بلا صلاحيات، شبكة مقطوعة، ملفات للقراءة فقط، حدود
  CPU/ذاكرة/عمليات).
- حدود الموارد العملية (rlimits) ومهلة قتل مجموعة الجلسة (ض5) بقيتا وتحسّنتا.

## أثر التحصين على الاختبارات والبوابات

- الحزمة الكاملة خضراء مع التغطية الإلزامية ≥95% (بوابة القائمة).
- اختبارات جديدة: `tests/test_security_hardening_v158.py` (25 اختبارًا) +
  3 اختبارات محدّثة في `tests/test_coder_sandbox.py`.
- تغيير عقد واحد معلن: مخطط خطوات `RepairPlan` اكتسب حقل `find` الاختياري
  (مطلوب لـ `edit`)، وموجه التخطيط في `src/coder/engine.py` محدّث؛ JSON القديم
  بلا `find` يبقى صالحًا للقراءة (قيمة افتراضية `""`) لكن `edit` بلا `find`
  يُرفض تحققًا وتنفيذًا.

## البصمة الزمنية

- الالتزام الأساس: `ed92aa9` — وأُعيد الأساس على `0916111` (ترقيات dependabot
  #75–#80 + دمج MIZAN) قبل الفتح، مع الحفاظ على الترقيات وإسقاط ما أضافه
  الماسح من تلوّث (ض10).
- الفرع: `feat/v1.58.0-security-hardening`.
- الإصدار: 1.58.0 (pyproject.toml + docs/openapi.yaml + src/__init__ الديناميكي).
