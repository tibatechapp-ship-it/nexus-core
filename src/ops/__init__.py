"""الطبقة التشغيلية الداخلية — خمسة مكوّنات مترابطة بعقود بيانات موحّدة.

المبدأ المعلن (v1.62.0): **بنية تشغيل داخلية** — مكوّنات صغيرة، عقود موحّدة،
جدولة صامتة، ولوحة واحدة، مع حجب كل فعل مؤثر (نشر/دمج/تثبيت) خلف مراجعة
بشرية افتراضيًا.

المكوّنات الخمسة وأدوارها:

* ``radar``      — رصد مصادر معلنة إلى إشارات ``Signal`` موحّدة (بلا شبكة افتراضيًا).
* ``indexer``    — فهرس الذكاء: تهذيب → تقطيع → تضمين محلي → استرجاع بميزانية توكن.
* ``verdict``    — عزل تنفيذي + فحوص ثابتة + حكم ثلاثي صادق (الافتراضي ``inconclusive``).
* ``tickets``    — كل حدث مؤثر يصير تذكرة بحالات محددة والنشر محجوب افتراضيًا.
* ``webqa``      — فحوص معايير الويب داخل CI فقط: بوابة حاجبة + بوابات استشارية.

ولأدوار الربط:

* ``store``      — قاعدة SQLite واحدة بنفس المخططات لكل المكوّنات + سجل تدقيق.
* ``runner``     — المجدول الموحّد: كل مهمة بمعزل فشل ومهلة، وملخص يومي واحد.
* ``dashboard``  — اللوحة الواحدة: لقطة عدّية + تقرير Markdown حتمي.

كل مكوّن يستهلك ويكتب نفس العقود في ``contracts.py`` — لا كود لصق بين
المكوّنات، واللوحة والتقارير تُبنى من المخزن الواحد مباشرة.

الحدود الصادقة المعلنة:

* لا شبكة افتراضيًا (الجلب الحي دالة مُمرَّرة اختيارية — يحترم ADR-0001).
* لا اعتماديات جديدة: stdlib خالص (sqlite3/hashlib/html.parser/subprocess).
* العزل على مستوى العملية (rlimits + بيئة مُنقَّحة)؛ الحجب الصارم للشبكة
  يتطلّب مشغّل حاويات خارجي — وهو خطّاف مُعلن لا افتراض.
"""

from __future__ import annotations

from src.ops.contracts import (
    ALLOWED_TRANSITIONS,
    FINAL_STATES,
    ORIGINS,
    TICKET_STATES,
    VERDICTS,
    Digest,
    GateResult,
    Signal,
    Ticket,
    Verdict,
)
from src.ops.store import OpsError, OpsStore

__all__ = [
    "ALLOWED_TRANSITIONS",
    "FINAL_STATES",
    "ORIGINS",
    "TICKET_STATES",
    "VERDICTS",
    "Digest",
    "GateResult",
    "OpsError",
    "OpsJob",
    "OpsRunner",
    "OpsStore",
    "Signal",
    "Ticket",
    "Verdict",
]


def __getattr__(name: str) -> object:
    """استيراد كسول لمكوّنات الطبقة — التبعيات الثقيلة لا تُحمَّل عند import.

    ``src.ops.runner`` يجلب radar/indexer/tickets؛ جعله كسولًا يبقي
    ``from src.ops import OpsStore`` خفيفًا كما كان، ويحمي دائرة
    الاستيراد عند استدعاء الطبقة من داخل novamind.
    """
    if name == "OpsJob":
        from src.ops.runner import OpsJob
        return OpsJob
    if name == "OpsRunner":
        from src.ops.runner import OpsRunner
        return OpsRunner
    raise AttributeError(f"الاسم غير معروف في src.ops: {name!r}")
