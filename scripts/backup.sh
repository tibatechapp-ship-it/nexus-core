#!/data/data/com.termux/files/usr/bin/bash
# nexus-core — نسخ احتياطي مجدول (بيانات المجلس/البناء/RAG + مستودع git كامل)
# مجدول في crontab الساعة 02:00. التدوير يلمس نسخنا فقط (nexus-*).
set -e
D=$(date +%Y%m%d-%H%M)
BK="$HOME/backups"
mkdir -p "$BK"

# 1) بيانات التشغيل (سياق المجلس، الحِزم المبنية، الكاش، قاعدة RAG)
tar czf "$BK/nexus-data-$D.tar.gz" -C "$HOME" \
    .nexus/data/council_history \
    .nexus/data/builds \
    .nexus/data/council_cache \
    .nexus/data/rag.db 2>/dev/null || true

# 2) المستودع كاملاً (كل الفروع والوسوم) كـ git bundle
git -C "$HOME/nexus-core" bundle create "$BK/nexus-repo-$D.bundle" --all 2>/dev/null || true

# 3) التدوير — نُبقي آخر 14 من كل نوع (لا نلمس أي ملف آخر)
ls -t "$BK"/nexus-data-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
ls -t "$BK"/nexus-repo-*.bundle 2>/dev/null | tail -n +15 | xargs -r rm -f

echo "backup done: $D"
