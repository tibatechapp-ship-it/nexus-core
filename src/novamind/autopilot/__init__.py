"""The Repository Autopilot — nexus-core agents that read, review and (later)
manage repositories on GitHub and GitLab.

Two read-only slices ship so far:

* **Slice 1 — SCM** (:mod:`src.novamind.autopilot.scm`): a provider-agnostic
  interface plus GitHub and GitLab adapters that return typed value objects and
  raise typed errors.
* **Slice 2 — readers** (:mod:`src.novamind.autopilot.readers`): fetch issues
  through any SCM and normalise them into structured, ranked :class:`~...task.Task`
  objects (kind, priority, areas, acceptance criteria, references).

No write, comment or PR surface exists yet.
"""

from __future__ import annotations
