import os
"""
NovaMind Dashboard - Simple web UI
Uses only http.server + HTML (no Flask)
"""
import json
import logging
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("web.dashboard")


# ═══════════════════════════════════════════════════════
#  HTML Template
# ═══════════════════════════════════════════════════════
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NovaMind Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, system-ui, sans-serif;
    background: #0d1117; color: #c9d1d9;
    padding: 20px; line-height: 1.6;
  }
  h1 { color: #58a6ff; margin-bottom: 20px; }
  .grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 15px; margin-bottom: 30px;
  }
  .card {
    background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; padding: 20px;
  }
  .card h3 { color: #8b949e; font-size: 0.9em; margin-bottom: 10px; }
  .card .value { font-size: 2em; color: #58a6ff; font-weight: bold; }
  .card .unit { color: #8b949e; font-size: 0.8em; }
  table {
    width: 100%; background: #161b22; border-radius: 8px;
    border-collapse: collapse; overflow: hidden;
  }
  th, td { padding: 12px; text-align: right; border-bottom: 1px solid #21262d; }
  th { background: #21262d; color: #8b949e; }
  .status-ok { color: #3fb950; }
  .status-warn { color: #d29922; }
  .status-fail { color: #f85149; }
  .section { margin-bottom: 30px; }
  .section h2 { color: #8b949e; margin-bottom: 15px; }
  a { color: #58a6ff; text-decoration: none; }
  .refresh {
    display: inline-block; padding: 8px 16px; background: #238636;
    color: white; border-radius: 6px; margin-bottom: 20px;
  }
  code {
    background: #21262d; padding: 2px 6px; border-radius: 4px;
    color: #f0f6fc; font-size: 0.9em;
  }
</style>
</head>
<body>
<h1>🧠 NovaMind Dashboard</h1>
<a class="refresh" href="/">🔄 Refresh</a>
<div id="content">Loading...</div>

<script>
async function loadData() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    render(data);
  } catch (e) {
    document.getElementById('content').innerHTML =
      '<div class="card"><h3>Error</h3><p>' + e + '</p></div>';
  }
}

function render(d) {
  const html = `
    <div class="grid">
      <div class="card">
        <h3>Tasks Processed</h3>
        <div class="value">${d.tasks_processed || 0}</div>
      </div>
      <div class="card">
        <h3>Files in Workspace</h3>
        <div class="value">${d.workspace_files || 0}</div>
      </div>
      <div class="card">
        <h3>Lessons Learned</h3>
        <div class="value">${d.lessons || 0}</div>
      </div>
      <div class="card">
        <h3>Tools Available</h3>
        <div class="value">${d.tools || 0}</div>
      </div>
      <div class="card">
        <h3>Knowledge Nodes</h3>
        <div class="value">${d.graph_nodes || 0}</div>
      </div>
      <div class="card">
        <h3>Graph Edges</h3>
        <div class="value">${d.graph_edges || 0}</div>
      </div>
    </div>

    <div class="section">
      <h2>📋 Recent Results</h2>
      <table>
        <tr><th>File</th><th>Status</th><th>Duration</th></tr>
        ${(d.recent_results || []).map(r => `
          <tr>
            <td><code>${r.file}</code></td>
            <td class="${r.status === 'passed' || r.status === 'fixed' ? 'status-ok' : 'status-fail'}">
              ${r.status}
            </td>
            <td>${r.duration}s</td>
          </tr>
        `).join('')}
      </table>
    </div>

    <div class="section">
      <h2>🧠 Recent Lessons</h2>
      <table>
        <tr><th>Lesson</th><th>Source</th></tr>
        ${(d.recent_lessons || []).map(l => `
          <tr>
            <td>${l.text}</td>
            <td><code>${l.source}</code></td>
          </tr>
        `).join('')}
      </table>
    </div>

    <div class="section">
      <h2>🕐 Server Time</h2>
      <p>${d.server_time}</p>
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


# ═══════════════════════════════════════════════════════
#  Request Handler
# ═══════════════════════════════════════════════════════
class DashboardHandler(BaseHTTPRequestHandler):
    def _html(self, html: str, code: int = 200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/dashboard":
            self._html(HTML_TEMPLATE)
        elif self.path == "/api/status":
            self._json(self._gather_status())
        elif self.path == "/api/tools":
            self._json(self._get_tools())
        elif self.path == "/health":
            self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)

    def _gather_status(self):
        from pathlib import Path
        workspace = Path(os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent))) / "workspace"

        # Tasks processed
        results_files = sorted(
            workspace.glob("*.result.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        recent_results = []
        passed = 0
        for rf in results_files[:10]:
            try:
                data = json.loads(rf.read_text(encoding="utf-8"))
                status = data.get("status", "?")
                if status in ("passed", "fixed"):
                    passed += 1
                recent_results.append({
                    "file": rf.stem.replace(".result", ""),
                    "status": status,
                    "duration": data.get("duration_sec", 0),
                })
            except Exception:
                pass

        # Workspace files
        workspace_files = len(list(workspace.glob("*.py")))

        # Lessons
        lessons_count = 0
        recent_lessons = []
        try:
            from core.semantic import semantic_memory
            lessons_count = semantic_memory.count()
            raw = semantic_memory.raw()
            for line in raw.split("\n")[-10:]:
                if line.startswith("- ["):
                    recent_lessons.append({
                        "text": line[:100],
                        "source": "semantic",
                    })
        except Exception:
            pass

        # Graph
        graph_nodes = 0
        graph_edges = 0
        try:
            from core.graph_memory import graph_memory
            stats = graph_memory.stats()
            graph_nodes = stats.get("total_nodes", 0)
            graph_edges = stats.get("total_edges", 0)
        except Exception:
            pass

        # Tools
        tools_count = 0
        try:
            from tools import registry
            tools_count = len(registry.list_tools())
        except Exception:
            pass

        return {
            "tasks_processed": len(results_files),
            "tasks_passed": passed,
            "workspace_files": workspace_files,
            "lessons": lessons_count,
            "recent_lessons": recent_lessons,
            "graph_nodes": graph_nodes,
            "graph_edges": graph_edges,
            "tools": tools_count,
            "recent_results": recent_results,
            "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    def _get_tools(self):
        try:
            from tools import registry
            return {
                "total": len(registry.list_tools()),
                "tools": registry.list_tools(),
            }
        except Exception as e:
            return {"error": str(e)}

    def log_message(self, *args):
        pass


# ═══════════════════════════════════════════════════════
#  Server
# ═══════════════════════════════════════════════════════
class DashboardServer:
    def __init__(self, port: int = 8000):
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        def _run():
            self.server = HTTPServer(("0.0.0.0", self.port),
                                     DashboardHandler)
            logger.info(f"dashboard on http://0.0.0.0:{self.port}")
            self.server.serve_forever()

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()


dashboard_server = DashboardServer(port=8000)


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)

    port = int(os.environ.get("DASHBOARD_PORT", "8000"))
    server = DashboardServer(port=port)
    server.start()

    print(f"Dashboard running at http://localhost:{port}")
    print("Press Ctrl+C to stop")

    try:
        import time
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop()
