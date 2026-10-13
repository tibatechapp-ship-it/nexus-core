"""The Repository Autopilot — nexus-core agents that read, review and (later)
manage repositories on GitHub and GitLab.

Slice 1 ships only the **read-only** SCM layer (see :mod:`src.novamind.autopilot.scm`):
a provider-agnostic interface plus GitHub and GitLab adapters that return typed
value objects and raise typed errors. No write, comment or PR surface exists yet.
"""

from __future__ import annotations
