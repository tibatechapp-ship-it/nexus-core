# العرض بنقرة واحدة عبر devcontainer (M3.4)

الوعد: **مستعرض نظيف يصل للوحة خلال خمس دقائق، بلا قراءة توثيق.**

## الخطوات

1. افتح المستودع في VS Code أو GitHub Codespaces (زر **Code → Codespaces**).
2. عند الطلب اختر **Reopen in Container** — البنية تُبنى تلقائياً:
   - تثبيت الحزمة وأدوات الفحص (`postCreateCommand`).
   - تشغيل لوحة القراءة-فقط تلقائياً على المنفذ 8000 (`postStartCommand`).
3. المتصفح يفتح اللوحة وحده (`onAutoForward: openBrowser`) — لا أوامر يدوية.

## ماذا سترى

- **مؤشرات حية (KPIs)** من سجلَّي الأثر والبوابة (M3.3) — أصفار إن كانت
  السجلات فارغة، وهذا طبيعي في حاوية جديدة.
- الوكلاء النشطون، المهام الجارية، آخر قرارات المجلس، آخر أحداث الأثر.

## تشغيل بديل بلا حاوية

```bash
pip install -e . && pip install uvicorn
python -m uvicorn src.web.app:app --port 8000
```

## فحص الصحة بعد الإقلاع

- `GET /dashboard` — صفحة القراءة-فقط مع قسم KPIs.
- `GET /api/kpis` — المؤشرات نفسها JSON لمستهلكات آلية.
- العرض التجريبي للمحرك بلا شبكة: `python scripts/coder_demo.py`.
- جناح التقييم بلا شبكة: `python -m src.evalsuite --limit 8`.
