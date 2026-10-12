# 🔐 Agent Permissions Matrix — NovaMind RBAC

Last updated: 2026-10-09 Total agents: 67 | Roles: 6 | Permissions: 30

## Roles

| Role       | Arabic            | Agents |
| ---------- | ----------------- | ------ |
| executive  | الإدارة التنفيذية | 3      |
| researcher | البحث             | 9      |
| engineer   | الهندسة           | 14     |
| quality    | الجودة            | 15     |
| automation | الأتمتة           | 3      |
| ops        | العمليات          | 1      |

## Permissions by Role

- executive: plan, approve, delegate, review, read_all, write_decisions, override
- researcher: read_all, analyze, document, search, gather_context
- engineer: read_code, write_code, edit_files, run_tests, run_commands, commit, install_deps,
  read_all
- quality: read_all, review_code, run_tests, audit, block_merge, report_issues
- automation: monitor, trigger, schedule, read_status, execute_scheduled, heal
- ops: read_all, monitor, diagnose, apply_fix, report_issues, heal

## Usage

```python
from hive.factory.guards import can_agent_use_tool
from nova.security.permissions import get_role_for_agent, get_permissions

if can_agent_use_tool("coder", "write_code"):
    pass  # allowed
```

## Audit Trail

Log: /var/log/hive/rbac_audit.jsonl
