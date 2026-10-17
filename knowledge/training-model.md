---
title: نموذج التدريب — ستّ طبقات
category: training
tags: training, layers, identity, memory, skills, gates, adversarial, self-loop
---

# نموذج التدريب (6 طبقات)

كل وكيل في nexus-core يمتلك نفس الطبقات الست التي "تُدرَّب" بها zyvo:

| # | الطبقة | المعنى | الخليّة في nexus-core |
|---|--------|--------|------------------------|
| 1 | الهوية Identity | system-prompt: من أنا، نبرتي، لغتي، خطوط الرفض | `BaseAgent.system_prompt` + `AgentManifest` |
| 2 | الذاكرة الساخنة Hot memory | يُحمَّل تلقائياً كل جلسة | `src/knowledge/` + `src/memory/` |
| 3 | المهارات أولاً Skills-first | حمّل SKILL.md المطابق **قبل** التنفيذ | `src/skills/loader.py` |
| 4 | البوّابات Gates | لا "تمّ" بلا أمر التحقق الحقيقي | `quality_gate` + بوّابات المستودع |
| 5 | العدائية Adversarial | متجهات هجوم يجب أن تصمد | `tests/adversarial/` + `src/security/` |
| 6 | الحلقة الذاتية Self-loop | تجربة → درس → مهارة → جينوم | `src/learning/` + `genome_v2` |

## مراحل التدريب الرسمية
```
FOUNDATION → SPECIALIZATION → SIMULATION → EVALUATION → TEAMWORK → FIELD → ADVANCED
                                                        ↘ RETRAINING (عند الهبوط)
```
- بوّابة كل مرحلة = `min_score` (افتراضي 0.7).
- التخرّج = `graduation_test` بـ `graduation_min_score ≥ 0.75`.
- شهادة **فقط** عند بلوغ العتبة — وإلا `needs_retraining` بلا شهادة.

## أنبوب التدريب العملي
`TrainingEngine` يقيس كل وحدة بمُقيِّم **حتمي** (يُشتقّ من الاسم) ثم:
يُخرّج شهادة، ويحوّل التشغيل إلى **درس** (field loop)، ويغذّي **جينوم** v2،
ويسمح للجينوم بأن **يتطوّر** (retrain) عند هبوط المكانة إلى probation.
