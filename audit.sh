#!/data/data/com.termux/files/usr/bin/bash
# Nexus Council -- environment audit v2 (no false alarms)
# ASCII-only output (monospace-safe). Addresses: server, real LLM, suite,
# UI-module duplication, git sync, memory, empty doc items, zyvo dupes.
cd "$HOME/nexus-core" || exit 1
G='\033[32m'; R='\033[31m'; Y='\033[33m'; B='\033[36m'; N='\033[0m'
ok(){   echo -e "  ${G}[OK]   $1${N}"; }
bad(){  echo -e "  ${R}[FAIL] $1${N}"; }
warn(){ echo -e "  ${Y}[WARN] $1${N}"; }
sec(){  echo; echo -e "${B}=== $1 ===${N}"; }

sec "1) SERVER LIVE"
H=$(curl -s -m 3 http://127.0.0.1:8000/api/health 2>/dev/null)
if [ -n "$H" ]; then
  ok "running"
  echo "$H" | python3 -c "import json,sys;h=json.load(sys.stdin);print('       version=%s builder=%s embeddings=%s' % (h.get('version'),h.get('builder'),h.get('embeddings')))" 2>/dev/null
else
  bad "down -- start: cd ~/nexus-core && termux-wake-lock && nohup python3 main.py > logs/main.log 2>&1 &"
fi

sec "2) REAL LLM PROVIDER (proper env, not Mock)"
export NOVAMIND_HOME="$HOME/nexus-core"
export PYTHONPATH="$HOME/nexus-core/src:$HOME/nexus-core"
[ -f .env ] && { set -a; . ./.env 2>/dev/null; set +a; }
python3 << 'PY'
import sys; sys.path.insert(0, '.')
try:
    from novamind.core.llm_router import LLMRouter
    o = LLMRouter().generate(prompt="say yes", system="answer with one word", max_tokens=5)
    print("       ok=%s provider=%s model=%s err=%s" % (o.get("ok"), o.get("provider"), o.get("model"), (o.get("error") or "")[:60]))
except Exception as e:
    print("       FAILED:", str(e)[:80])
PY

sec "3) FULL TEST SUITE"
python3 -m pytest tests/ -q -p no:cacheprovider 2>&1 | tail -1

sec "4) v1.11 UI MODULES (duplication check)"
NMOD=$(grep -c "v1.11 features module"   index.html)
WH=$(grep -c "doWrap('handleEvent'"      index.html)
WD=$(grep -c "doWrap('deliberate'"       index.html)
WC=$(grep -c "doWrap('command'"          index.html)
NS=$(grep -c "<script"                   index.html)
echo "       module markers=$NMOD script tags=$NS wraps: handleEvent=$WH deliberate=$WD command=$WC"
if [ "$NMOD" -gt 1 ] || [ "$WH" -gt 1 ] || [ "$WD" -gt 1 ] || [ "$WC" -gt 1 ]; then
  warn "duplicated modules -> double sounds / double speech; merge them"
else
  ok "single module"
fi
grep -q "SpeechRecognition" index.html && ok "voice input (STT) present in code" || warn "voice input missing in code"
grep -q "speechSynthesis"   index.html && ok "TTS present in code"              || warn "TTS missing in code"

sec "5) GIT SYNC"
L=$(git rev-parse HEAD)
for REM in origin gitlab; do
  RM=$(git ls-remote "$REM" feature/landing-page 2>/dev/null | cut -f1)
  if [ "$L" = "$RM" ]; then ok "$REM in sync ($L)"; else warn "$REM diverged (local=$L remote=$RM)"; fi
done
BR=$(git branch --show-current); echo "       branch=$BR HEAD=$(git rev-parse --short HEAD)"

sec "6) RESOURCES"
AV=$(free -m | awk '/^Mem:/{print $7}'); SW=$(free -m | awk '/^Swap:/{print $3}')
[ "$AV" -lt 800 ] && warn "only ${AV}MB RAM available -- process-kill risk" || ok "RAM available: ${AV}MB"
[ "$SW" -gt 1500 ] && warn "swap used ${SW}MB -- check zyvo duplication" || ok "swap used: ${SW}MB"

sec "7) MODULE INTEGRITY"
for m in recommend history cache rag_bridge topics members builder; do
  f="src/council/$m.py"
  [ -f "$f" ] && ok "$f" || warn "$f MISSING"
done

sec "8) ZYVO PROCESS DUPLICATION (port 4142)"
PIDS=$(pgrep -f "zyvo[.]bin --port 4142")
DUP=$(echo "$PIDS" | grep -c . )
ORPH=0
for pid in $PIDS; do
  pp=$(awk '{print $4}' /proc/$pid/stat 2>/dev/null)
  [ "$pp" = "1" ] && ORPH=$((ORPH + 1))
done
echo "       zyvo.bin on :4142 -> ${DUP} instance(s), orphaned(ppid=1)=${ORPH}"
if [ "$DUP" -gt 1 ]; then warn "duplicate zyvo brains on :4142 -- restart: sv restart zyvo-telegram"; else ok "single instance"; fi
[ "$DUP" -eq 0 ] && warn "no brain on :4142 -- the telegram bot has no server"

sec "9) RECOMMENDATION FILTER (last history entry)"
python3 << 'PY'
import json, glob, os, re, sys
sys.path.insert(0, '.')
fs = sorted(glob.glob(os.path.expanduser('~/.nexus/data/council_history/*.json')), key=os.path.getmtime)
if not fs:
    print("       no history files"); raise SystemExit
r = json.load(open(fs[-1]))
print("       file=%s" % os.path.basename(fs[-1]))
print("       query_chars=%d" % len(r.get('query') or ''))
tr = r.get('transcript', [])
recs = [m.group(1) for e in tr
        for m in [re.search(r'\[التوصية:\s*([^\]]+)\]', e.get('response', ''))] if m]
print("       raw [reco] tags found=%d" % len(recs))
try:
    from src.council.recommend import extract_recommendation
    out = extract_recommendation(tr)
    print("       extracted: len=%d empty=%s" % (len(out), out == ""))
except Exception as ex:
    print("       extract failed:", str(ex)[:60])
PY

echo; echo -e "${B}=== END ===${N}"
