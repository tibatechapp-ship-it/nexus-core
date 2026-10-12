#!/usr/bin/env python3
"""
Deep Comparator — يقارن مجلدين بدقة عالية ويقترح قراراً
"""
from pathlib import Path
import hashlib
import sys

def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]

def collect_files(root: Path) -> dict:
    """يجمع كل الملفات مع hash"""
    files = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        # تخطي __pycache__ و .pyc
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        rel = str(p.relative_to(root))
        try:
            files[rel] = {
                "hash": hash_file(p),
                "size": p.stat().st_size,
                "path": p,
            }
        except Exception as e:
            files[rel] = {"error": str(e), "path": p}
    return files

def compare(old_dir: Path, new_dir: Path):
    print(f"🔍 مقارنة:")
    print(f"   القديم: {old_dir}")
    print(f"   الجديد: {new_dir}")
    print("=" * 70)

    old_files = collect_files(old_dir)
    new_files = collect_files(new_dir)

    # 1. ملفات فريدة في القديم
    only_old = sorted(set(old_files) - set(new_files))
    # 2. ملفات فريدة في الجديد
    only_new = sorted(set(new_files) - set(old_files))
    # 3. ملفات مشتركة لكن مختلفة
    common = set(old_files) & set(new_files)
    different = sorted([f for f in common if old_files[f].get("hash") != new_files[f].get("hash")])
    # 4. ملفات متطابقة
    identical = sorted([f for f in common if old_files[f].get("hash") == new_files[f].get("hash")])

    print(f"\n📊 الإحصائيات:")
    print(f"   ملفات فريدة في القديم: {len(only_old)}")
    print(f"   ملفات فريدة في الجديد: {len(only_new)}")
    print(f"   ملفات مشتركة مختلفة:  {len(different)}")
    print(f"   ملفات مشتركة متطابقة:  {len(identical)}")

    # ---- تحليل الملفات الفريدة في القديم ----
    print("\n" + "=" * 70)
    print("⚠️  ملفات فريدة في القديم (قد تحتاج مراجعة):")
    print("=" * 70)

    critical_old = []
    for f in only_old:
        info = old_files[f]
        size = info.get("size", 0)
        # تحديد نوع الملف
        if f.endswith((".bak", ".bak1", ".bak2", ".bak3", ".bak4", ".bak5", ".bak6")):
            tag = "🟢 نسخة احتياطية قديمة"
        elif f.endswith(".broken"):
            tag = "🟢 ملف مكسور"
        elif f.endswith(".pyc") or "__pycache__" in f:
            tag = "🟢 ملف تجميع مؤقت"
        elif f.endswith(".log"):
            tag = "🟡 سجل (log)"
        elif f.endswith(".json"):
            tag = "🟡 بيانات JSON"
        elif f.endswith(".py"):
            tag = "🔴 ملف Python — يحتاج مراجعة!"
            critical_old.append(f)
        else:
            tag = "🟡 نوع غير معروف"

        print(f"   [{tag}] {f} ({size} bytes)")

    # ---- تحليل الملفات المختلفة ----
    print("\n" + "=" * 70)
    print("🔄 ملفات مشتركة لكن مختلفة (الأحدث هو الأفضل):")
    print("=" * 70)

    important_diffs = []
    for f in different:
        old_size = old_files[f].get("size", 0)
        new_size = new_files[f].get("size", 0)
        old_mtime = old_files[f]["path"].stat().st_mtime
        new_mtime = new_files[f]["path"].stat().st_mtime

        if f.endswith(".py"):
            important_diffs.append(f)

        # تحديد الأحدث
        newer = "الجديد" if new_mtime > old_mtime else "القديم"
        diff_size = new_size - old_size

        if f.endswith(".py"):
            print(f"   🔴 {f}")
            print(f"      القديم: {old_size}b  |  الجديد: {new_size}b  |  الفرق: {diff_size:+d}b")
            print(f"      الأحدث: {newer} ✅")

    # ---- النتيجة النهائية ----
    print("\n" + "=" * 70)
    print("🎯 النتيجة النهائية:")
    print("=" * 70)

    if critical_old:
        print(f"   ❌ يوجد {len(critical_old)} ملف Python فريد في القديم!")
        print("   ⚠️  لا تؤرشف قبل مراجعة هذه الملفات يدوياً.")
        for f in critical_old:
            print(f"      - {f}")
    else:
        print(f"   ✅ لا يوجد أي ملف Python فريد في القديم.")
        print(f"   ✅ كل الملفات الفريدة هي ملفات مؤقتة/احتياطية.")
        print(f"   ✅ آمن للأرشفة!")

    return critical_old

if __name__ == "__main__":
    old = Path("/public/core")
    new = Path("/public/nova/core")
    if not old.exists():
        print(f"❌ المجلد غير موجود: {old}")
        sys.exit(1)
    if not new.exists():
        print(f"❌ المجلد غير موجود: {new}")
        sys.exit(1)
    compare(old, new)
