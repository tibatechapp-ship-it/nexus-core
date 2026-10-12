"""
Dashboard v2 - Live stats with charts (Arabic RTL)
Reads from real NovaMind modules.
"""
import json
import logging
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone
import os

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("web.dashboard_v2")


HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NovaMind Dashboard v2</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
  h1 { color: #58a6ff; margin-bottom: 20px; font-size: 1.6em; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 30px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 18px; }
  .card h3 { color: #8b949e; font-size: 0.8em; margin-bottom: 8px; font-weight: normal; }
  .card .value { font-size: 2em; color: #58a6ff; font-weight: bold; line-height: 1.1; }
  .card .sub { color: #8b949e; font-size: 0.75em; margin-top: 4px; }
  .card.green .value { color: #3fb950; }
  .card.orange .value { color: #d29922; }
  .card.purple .value { color: #bc8cff; }
  .chart-bar { background: #21262d; height: 26px; border-radius: 4px; margin: 8px 0; position: relative; overflow: hidden; }
  .chart-fill { background: linear-gradient(90deg, #3fb950, #58a6ff); height: 100%; transition: width 0.5s; }
  .chart-label { position: absolute; top: 4px; right: 10px; font-size: 0.85em; z-index: 2; font-weight: bold; }
  table { width: 100%; background: #161b22; border-collapse: collapse; border-radius: 8px; overflow: hidden; margin-bottom: 20px; }
  th, td { padding: 10px 12px; text-align: right; border-bottom: 1px solid #21262d; font-size: 0.9em; }
  th { background: #21262d; color: #8b949e; font-size: 0.8em; font-weight: normal; }
  tr:last-child td { border-bottom: none; }
  .status-ok { color: #3fb950; font-weight: bold; }
  .status-err { color: #f85149; font-weight: bold; }
  .status-warn { color: #d29922; font-weight: bold; }
  .refresh { display: inline-block; padding: 8px 16px; background: #238636; color: white; border-radius: 6px; text-decoration: none; margin-bottom: 20px; cursor: pointer; border: none; font-size: 0.9em; }
  .refresh:hover { background: #2ea043; }
  .section { margin-bottom: 30px; }
  .section h2 { color: #8b949e; margin-bottom: 12px; border-bottom: 1px solid #21262d; padding-bottom: 8px; font-size: 1.1em; font-weight: normal; }
  code { background: #21262d; padding: 2px 6px; border-radius: 4px; color: #f0f6fc; font-size: 0.85em; }
  .live { color: #3fb950; animation: pulse 2s infinite; font-size: 0.7em; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
  .footer { color: #484f58; font-size: 0.75em; text-align: center; margin-top: 40px; padding-top: 20px; border-top: 1px solid #21262d; }
</style>
</head>
<body>
<h1>🧠 NovaMind Dashboard <span class="live">● LIVE</span></h1>
<button class="refresh" onclick="loadData()">🔄 تحديث</button>

<div id="content">جاري التحميل...</div>

<div class="footer">
  NovaMind Pro v6 — نظام مراجعة ذاتي التعلم<br>
  آخر تحديث: <span id="lastupdate">-</span>
</div>

<script>
async function loadData() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    render(data);
    document.getElementById('lastupdate').textContent = new Date().toLocaleTimeString('ar-EG');
  } catch (e) {
    document.getElementById('content').innerHTML =
      '<div class="card"><h3>خطأ في الاتصال</h3><p>' + e + '</p></div>';
  }
}

function render(d) {
  const successRate = d.tasks_processed > 0
    ? Math.round(d.tasks_passed / d.tasks_processed * 100)
    : 0;

  const html = `
    <div class="grid">
      <div class="card">
        <h3>📋 المهام المعالجة</h3>
        <div class="value">${d.tasks_processed || 0}</div>
        <div class="sub">✅ ${d.tasks_passed || 0} نجحت</div>
      </div>
      <div class="card green">
        <h3>🎯 معدل النجاح</h3>
        <div class="value">${successRate}%</div>
      </div>
      <div class="card">
        <h3>🧠 الدروس (Semantic)</h3>
        <div class="value">${d.lessons || 0}</div>
      </div>
      <div class="card purple">
        <h3>🕸️ Graph Nodes</h3>
        <div class="value">${d.graph_nodes || 0}</div>
        <div class="sub">${d.graph_edges || 0} علاقة · ${d.graph_keywords || 0} كلمة</div>
      </div>
      <div class="card orange">
        <h3>🛠️ الأدوات</h3>
        <div class="value">${d.tools || 0}</div>
      </div>
      <div class="card green">
        <h3>📊 الأنماط المكتسبة</h3>
        <div class="value">${d.total_learned || 0}</div>
        <div class="sub">${d.unique_patterns || 0} فريدة</div>
      </div>
    </div>

    <div class="section">
      <h2>📈 معدل النجاح الكلي</h2>
      <div class="chart-bar">
        <div class="chart-fill" style="width: ${successRate}%"></div>
        <div class="chart-label">${successRate}%</div>
      </div>
    </div>

    <div class="section">
      <h2>📋 آخر النتائج (Workspace)</h2>
      <table>
        <tr><th>الملف</th><th>الحالة</th><th>المدة</th></tr>
        ${(d.recent_results || []).length === 0
          ? '<tr><td colspan="3" style="text-align:center;color:#8b949e;">لا نتائج بعد</td></tr>'
          : (d.recent_results || []).slice(0, 10).map(r => `
            <tr>
              <td><code>${r.file}</code></td>
              <td class="${['passed','fixed','success','ok'].includes(r.status) ? 'status-ok' : 'status-err'}">
                ${r.status}
              </td>
              <td>${r.duration || 0}s</td>
            </tr>
          `).join('')}
      </table>
    </div>

    <div class="section">
      <h2>🧠 أهم الأنماط المكتسبة</h2>
      <table>
        <tr><th>النمط</th><th>مرات الظهور</th></tr>
        ${(d.top_patterns || []).length === 0
          ? '<tr><td colspan="2" style="text-align:center;color:#8b949e;">لا أنماط بعد</td></tr>'
          : (d.top_patterns || []).map(p => `
            <tr>
              <td>${p[0]}</td>
              <td><strong>${p[1]}</strong></td>
            </tr>
          `).join('')}
      </table>
    </div>

    <div class="section">
      <h2>🕐 وقت السيرفر</h2>
      <p style="color:#8b949e;font-size:0.9em;">${d.server_time}</p>
    </div>
  `;
  document.getElementById('content').innerHTML = html;
}

loadData();
setInterval(loadData, 5000);
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html, code=200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/dashboard"):
            self._html(HTML)
        elif self.path == "/api/status":
            self._json(self._status())
        elif self.path == "/health":
            self._json({"ok": True, "time": datetime.now(timezone.utc).isoformat()})
        else:
            self._json({"error": "not found"}, 404)

    def _status(self):
        workspace = Path(os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent))) / "workspace"
        results = sorted(workspace.glob("*.result.json"),
                         key=lambda p: p.stat().st_mtime,
                         reverse=True)

        recent = []
        passed = 0
        for rf in results[:20]:
            try:
                d = json.loads(rf.read_text(encoding="utf-8"))
                status = d.get("status", "?")
                if status in ("passed", "fixed", "success", "ok"):
                    passed += 1
                recent.append({
                    "file": rf.stem.replace(".result", ""),
                    "status": status,
                    "duration": d.get("duration_sec", 0),
                })
            except Exception:
                pass

        lessons = 0
        try:
            from core.semantic import semantic_memory
            lessons = semantic_memory.count()
        except Exception:
            pass

        gn, ge, gk = 0, 0, 0
        try:
            from core.graph_memory import graph_memory
            s = graph_memory.stats()
            gn = s.get("total_nodes", 0)
            ge = s.get("total_edges", 0)
            gk = s.get("total_keywords", 0)
        except Exception:
            pass

        tools = 0
        try:
            from tools import registry
            tools = len(registry.list_tools())
        except Exception:
            pass

        learned = 0
        unique_patterns = 0
        top_patterns = []
        try:
            from core.learning_loop import learning_loop
            st = learning_loop.stats()
            learned = st.get("total_learned", 0)
            unique_patterns = st.get("unique_patterns", 0)
            top_patterns = st.get("top_patterns", [])
        except Exception:
            pass

        return {
            "tasks_processed": len(results),
            "tasks_passed": passed,
            "workspace_files": len(list(workspace.glob("*.py"))),
            "lessons": lessons,
            "graph_nodes": gn,
            "graph_edges": ge,
            "graph_keywords": gk,
            "tools": tools,
            "prs_reviewed": 0,
            "prs_fixed": 0,
            "total_learned": learned,
            "unique_patterns": unique_patterns,
            "top_patterns": top_patterns,
            "recent_results": recent,
            "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    def log_message(self, *args):
        pass


class DashboardV2Server:
    def __init__(self, port=8000):
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        def _run():
            self.server = HTTPServer(("0.0.0.0", self.port), DashboardHandler)
            logger.info(f"Dashboard v2 on port {self.port}")
            self.server.serve_forever()
        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()


dashboard_v2 = DashboardV2Server(port=8000)

if __name__ == "__main__":
    import logging as _log
    _log.basicConfig(level=_log.INFO)
    dashboard_v2.start()
    print(f"✅ Dashboard v2: http://localhost:{dashboard_v2.port}")
    print("Press Ctrl+C to stop")
    try:
        import time
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        dashboard_v2.stop()
