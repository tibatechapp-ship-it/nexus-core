# Docker execution sandbox

The existing src/coder/sandbox.py is a Termux-compatible workspace and
resource-limited subprocess runner. It is not an OS security boundary and
must not be trusted with arbitrary hostile code.

src/coder/container_sandbox.py adds an opt-in Docker boundary. It fails closed
unless the operator sets NEXUS_ENABLE_CONTAINER_SANDBOX=1, the caller passes
enabled=True, and the invocation passes approved=True. Images must be pinned
by sha256 digest and preloaded locally; image pulls are disabled.

Enforced options: network=none, read-only container root, one writable task
workspace, all Linux capabilities dropped, no-new-privileges, non-root UID,
PID (1–256), memory (128 MiB–16 GiB), CPU (0.1–8 cores), time (1–300 s),
argument-count/size and output bounds, and a bounded noexec/nosuid/nodev /tmp.
No host environment variables or credentials are forwarded.

Operational requirements:
- Use rootless Docker on a dedicated worker.
- Never expose the Docker socket to agent-controlled code.
- Review and pin the minimal runner image independently of the target repo.
- Treat the kernel, daemon, runtime and host configuration as trusted computing base.
- Do not globally enable the opt-in in a multi-tenant service.

This change does not provision cloud resources, install Docker, pull images,
or automatically connect the runner to the orchestration loop. Production
integration still requires durable approval records, per-task audit IDs,
worker lifecycle management and image provenance verification.
The existing Termux runner and read-only local tools remain unchanged.
