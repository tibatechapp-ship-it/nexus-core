import os
"""Hive Dashboard — Minimal Clean."""
from aiohttp import web
import logging
import jinja2
import aiohttp_jinja2
from pathlib import Path

log = logging.getLogger("Dashboard")
TEMPLATES = Path(__file__).parent / "templates"


@aiohttp_jinja2.template("home.html")
async def home(request):
    return {"page": "home"}


async def status_api(request):
    try:
        from ..orchestrator import get_orchestrator
        return web.json_response(get_orchestrator().status())
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def health_api(request):
    return web.json_response({"ok": True})


async def report_api(request):
    try:
        from ..orchestrator import get_orchestrator
        from ..report_generator import get_report_generator
        orch = get_orchestrator()
        rep = get_report_generator(orch)
        content = await rep.generate_daily_report()
        return web.json_response({"ok": True, "report": content})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def create_app():
    app = web.Application()
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(str(TEMPLATES)))

    app.router.add_get("/", home)
    app.router.add_get("/status", status_api)
    app.router.add_get("/health", health_api)
    app.router.add_get("/api/report", report_api)
    return app


def run_dashboard(host=None, port=8080):
    host = host or os.getenv("NEXUS_DASH_BIND", "127.0.0.1")
    app = create_app()
    log.info("Dashboard: http://" + host + ":" + str(port))
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_dashboard()
