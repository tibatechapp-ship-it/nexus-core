#!/bin/sh
# ═══════════════════════════════════════════════════════
#  فحص بيئة Alpine قبل التثبيت
#  Usage: sh /root/check_env.sh
# ═══════════════════════════════════════════════════════

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { printf "${GREEN}  ✅ %s${NC}\n" "$1"; }
miss() { printf "${RED}  ❌ %s${NC}\n" "$1"; }
warn() { printf "${YELLOW}  ⚠️  %s${NC}\n" "$1"; }
info() { printf "${BLUE}  ℹ️  %s${NC}\n" "$1"; }

echo ""
echo "═══════════════════════════════════════════════════════"
echo "   🔍 فحص بيئة Alpine Linux"
echo "═══════════════════════════════════════════════════════"
echo ""

# ─── 1. معلومات النظام ──────────────────────────────
echo "【1】معلومات النظام"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    info "التوزيعة: ${PRETTY_NAME:-unknown}"
    info "الإصدار: ${VERSION_ID:-unknown}"
else
    warn "لا يمكن قراءة /etc/os-release"
fi
info "النواة: $(uname -r)"
info "المعمارية: $(uname -m)"
info "المستخدم: $(whoami)"
info "المسار الحالي: $(pwd)"
echo ""

# ─── 2. مدير الحزم ────────────────────────────────
echo "【2】مدير الحزم (apk)"
if command -v apk >/dev/null 2>&1; then
    ok "apk مثبّت: $(apk --version 2>&1 | head -1)"
    if apk info -e apk-tools >/dev/null 2>&1; then
        info "apk-tools محدّث"
    fi
else
    miss "apk غير موجود — هذه ليست Alpine!"
fi
echo ""

# ─── 3. الأدوات الأساسية ──────────────────────────
echo "【3】الأدوات الأساسية"

check_cmd() {
    name="$1"
    pkg="$2"
    if command -v "$name" >/dev/null 2>&1; then
        ver=$("$name" --version 2>&1 | head -1 | cut -c1-60)
        ok "$name — $ver"
    else
        miss "$name — غير مثبّت (apk add $pkg)"
    fi
}

check_cmd "sh"        "busybox"
check_cmd "bash"      "bash"
check_cmd "python3"   "python3"
check_cmd "pip3"      "py3-pip"
check_cmd "git"       "git"
check_cmd "nano"      "nano"
check_cmd "curl"      "curl"
check_cmd "wget"      "wget"
check_cmd "ssh"       "openssh-client"
check_cmd "rsync"     "rsync"
check_cmd "tmux"      "tmux"
check_cmd "htop"      "htop"
check_cmd "mc"        "mc"
check_cmd "gcc"       "build-base"
check_cmd "make"      "build-base"
echo ""

# ─── 4. فحص Python ────────────────────────────────
echo "【4】تفاصيل Python"
if command -v python3 >/dev/null 2>&1; then
    PY_VER=$(python3 --version 2>&1)
    PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
    ok "$PY_VER"
    info "المسار: $(command -v python3)"
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
        warn "Python 3.11+ يتطلب --break-system-packages عند pip install"
    fi
    if command -v pip3 >/dev/null 2>&1; then
        info "pip3: $(pip3 --version 2>&1 | head -1)"
    fi
else
    miss "Python3 غير مثبّت"
fi
echo ""

# ─── 5. فحص مكتبات Python المطلوبة ────────────────
echo "【5】مكتبات Python المطلوبة"

check_py() {
    mod="$1"
    pkgname="$2"
    if python3 -c "import $mod" 2>/dev/null; then
        ver=$(python3 -c "import $mod; print(getattr($mod, '__version__', 'unknown'))" 2>/dev/null)
        ok "$mod ($ver)"
    else
        miss "$mod — غير مثبّت (pip3 install --break-system-packages $pkgname)"
    fi
}

if command -v python3 >/dev/null 2>&1; then
    check_py "telegram"      "python-telegram-bot"
    check_py "google.genai"  "google-genai"
    check_py "tenacity"      "tenacity"
    check_py "dotenv"        "python-dotenv"
    check_py "asyncio"       "builtin"
    check_py "json"          "builtin"
else
    warn "تخطى — Python غير مثبّت"
fi
echo ""

# ─── 6. فحص Git ──────────────────────────────────
echo "【6】إعدادات Git"
if command -v git >/dev/null 2>&1; then
    GN=$(git config --global user.name 2>/dev/null)
    GE=$(git config --global user.email 2>/dev/null)
    if [ -n "$GN" ]; then
        ok "user.name = $GN"
    else
        warn "user.name غير معد (git config --global user.name 'اسمك')"
    fi
    if [ -n "$GE" ]; then
        ok "user.email = $GE"
    else
        warn "user.email غير معد (git config --global user.email 'بريدك')"
    fi
else
    warn "تخطى — git غير مثبّت"
fi
echo ""

# ─── 7. فحص الشبكة ────────────────────────────────
echo "【7】الاتصال بالشبكة"
if command -v ping >/dev/null 2>&1; then
    if ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
        ok "الاتصال بالإنترنت يعمل (8.8.8.8)"
    else
        warn "لا يمكن الوصول إلى 8.8.8.8"
    fi
else
    info "ping غير متوفر (طبيعي في Alpine)"
fi

if command -v curl >/dev/null 2>&1; then
    if curl -s --max-time 5 -o /dev/null https://pypi.org; then
        ok "الوصول إلى pypi.org ناجح (لتثبيت pip)"
    else
        miss "لا يمكن الوصول إلى pypi.org"
    fi
    if curl -s --max-time 5 -o /dev/null https://github.com; then
        ok "الوصول إلى github.com ناجح"
    else
        warn "لا يمكن الوصول إلى github.com"
    fi
fi
echo ""

# ─── 8. المساحة والذاكرة ──────────────────────────
echo "【8】الموارد المتاحة"
if command -v df >/dev/null 2>&1; then
    SPACE=$(df -h / 2>/dev/null | awk 'NR==2 {print $4}')
    [ -n "$SPACE" ] && info "المساحة الحرة: $SPACE"
fi
if [ -f /proc/meminfo ]; then
    MEM_TOTAL=$(awk '/MemTotal/ {printf "%.0f MB", $2/1024}' /proc/meminfo)
    MEM_FREE=$(awk  '/MemFree/  {printf "%.0f MB", $2/1024}' /proc/meminfo)
    info "الذاكرة الكلية: $MEM_TOTAL"
    info "الذاكرة الحرة: $MEM_FREE"
fi
echo ""

# ─── 9. الملخص ────────────────────────────────────
echo "═══════════════════════════════════════════════════════"
echo "   📌 أوامر التثبيت المقترحة"
echo "═══════════════════════════════════════════════════════"
echo ""

NEEDED=""
command -v bash     >/dev/null 2>&1 || NEEDED="$NEEDED bash"
command -v python3  >/dev/null 2>&1 || NEEDED="$NEEDED python3"
command -v pip3     >/dev/null 2>&1 || NEEDED="$NEEDED py3-pip"
command -v git      >/dev/null 2>&1 || NEEDED="$NEEDED git"
command -v nano     >/dev/null 2>&1 || NEEDED="$NEEDED nano"
command -v curl     >/dev/null 2>&1 || NEEDED="$NEEDED curl"
command -v rsync    >/dev/null 2>&1 || NEEDED="$NEEDED rsync"
command -v tmux     >/dev/null 2>&1 || NEEDED="$NEEDED tmux"
command -v htop     >/dev/null 2>&1 || NEEDED="$NEEDED htop"

if [ -n "$NEEDED" ]; then
    echo "الحزم الناقصة:"
    echo ""
    echo "  apk add$NEEDED"
    echo ""
else
    echo "✅ جميع الحزم الأساسية مثبتة."
    echo ""
fi

PY_NEEDED=""
python3 -c "import telegram"    2>/dev/null || PY_NEEDED="$PY_NEEDED python-telegram-bot"
python3 -c "import google.genai" 2>/dev/null || PY_NEEDED="$PY_NEEDED google-genai"
python3 -c "import tenacity"    2>/dev/null || PY_NEEDED="$PY_NEEDED tenacity"
python3 -c "import dotenv"      2>/dev/null || PY_NEEDED="$PY_NEEDED python-dotenv"

if [ -n "$PY_NEEDED" ]; then
    echo "مكتبات Python الناقصة:"
    echo ""
    echo "  pip3 install --break-system-packages$PY_NEEDED"
    echo ""
else
    echo "✅ جميع مكتبات Python مثبتة."
    echo ""
fi

echo "═══════════════════════════════════════════════════════"
echo "   انتهى الفحص."
echo "═══════════════════════════════════════════════════════"
echo ""
