"""ProjectManager — يدير المهام ويتتبع التقدم."""
from novamind.base import BaseAgent
from datetime import datetime
from pathlib import Path
import json
import logging

log = logging.getLogger("ProjectManager")


class ProjectManager(BaseAgent):
    NAME = "pm"
    DESCRIPTION = "يدير المهام، يتتبع التقدم، يزيل العقبات"
    ROLE = "executive"
    LEVEL = 4
    CAPABILITIES = [
        "create_task", "assign_task", "track_progress",
        "report_status", "identify_blockers", "prioritize",
        "create_sprint", "burndown", "pm",
    ]

    def __init__(self):
        super().__init__()
        self.state_file = Path("/var/log/novamind/pm_state.json")
        self.state = self._load_state()

    def _load_state(self):
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                pass
        return {"tasks": [], "sprints": [], "stats": {}}

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def _register_tools(self):
        self.tools = {
            "create_task": self._create_task,
            "list_tasks": self._list_tasks,
            "update_task": self._update_task,
        }

    async def handle(self, task):
        action = task.get("action", "").lower()
        params = task.get("params", {})

        try:
            if "create" in action and "task" in action:
                return self._create_task(params)

            if "list" in action and "task" in action:
                return self._list_tasks(params)

            if "update" in action or "track" in action:
                return self._update_task(params)

            if "report" in action or "status" in action:
                return self._report_status(params)

            if "blocker" in action:
                return self._identify_blockers(params)

            return {"ok": True, "result": f"PM: {action}"}

        except Exception as e:
            log.exception("ProjectManager failed")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _create_task(self, params):
        """أنشئ مهمة."""
        task = {
            "id": f"TASK-{len(self.state['tasks']) + 1:04d}",
            "title": params.get("title", "Untitled"),
            "assignee": params.get("assignee", "unassigned"),
            "priority": params.get("priority", "medium"),
            "status": "todo",
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat(),
            "description": params.get("description", ""),
        }
        self.state["tasks"].append(task)
        self._save_state()
        log.info(f"✅ Task created: {task['id']}")
        return {"ok": True, "result": task}

    def _list_tasks(self, params):
        """اعرض المهام."""
        status = params.get("status", "all")
        tasks = self.state["tasks"]
        if status != "all":
            tasks = [t for t in tasks if t["status"] == status]
        return {"ok": True, "result": {"count": len(tasks), "tasks": tasks}}

    def _update_task(self, params):
        """حدّث مهمة."""
        task_id = params.get("id")
        for t in self.state["tasks"]:
            if t["id"] == task_id:
                t["status"] = params.get("status", t["status"])
                t["updated"] = datetime.now().isoformat()
                self._save_state()
                return {"ok": True, "result": t}
        return {"ok": False, "error": f"task {task_id} not found"}

    def _report_status(self, params):
        """تقرير الحالة."""
        tasks = self.state["tasks"]
        by_status = {}
        for t in tasks:
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        return {
            "ok": True,
            "result": {
                "total": len(tasks),
                "by_status": by_status,
                "by_assignee": self._by_assignee(),
            },
        }

    def _identify_blockers(self, params):
        """حدّد العقبات."""
        blockers = [
            t for t in self.state["tasks"]
            if t.get("blocked") or t["status"] == "blocked"
        ]
        return {"ok": True, "result": {"blockers": blockers, "count": len(blockers)}}

    def _by_assignee(self):
        result = {}
        for t in self.state["tasks"]:
            a = t["assignee"]
            result[a] = result.get(a, 0) + 1
        return result

# Auto-instance for registry
project_manager = ProjectManager()
