# GLM connectors — self-hosted GLM weights + cloud fallback

> موصلات GLM: الأوزان المفتوحة محليًا مع احتياط سحابي — مهمتا M1.3 وM1.4 من
> خطة الـ90 يوماً لطبقة وكيل البرمجة فوق nexus-core.

Three BYOK providers were added to the connector layer
(`connectors/registry.py`), all honouring the same
`BaseConnector.generate(prompt, system_prompt) -> {"ok": ..., "reply"|"error": ...}`
contract used by every other provider:

| Provider id | Class | Purpose |
|---|---|---|
| `glm-local` | `connectors/glm_local.py::GlmLocalConnector` | Self-hosted GLM behind any OpenAI-compatible server (vLLM / SGLang / MLX bridges) |
| `glm-cloud` | `connectors/glm_cloud.py::GlmCloudConnector` | Z.AI-hosted GLM — the paid fallback path |
| `glm` | `connectors/glm_cloud.py::GlmFailoverConnector` | Local-first wrapper with automatic failover to the cloud |

## Environment variables

Read lazily at call time (never at import), mirroring the BYOK purity rule:

| Variable | Default | Used by |
|---|---|---|
| `GLM_LOCAL_URL` | `http://127.0.0.1:8000/v1/chat/completions` | `glm-local` (and the local leg of `glm`) |
| `GLM_MODEL` | `zai-org/GLM-5.3` | `glm-local` |
| `GLM_CLOUD_BASE` | `https://api.z.ai/api/paas/v4` | `glm-cloud` (and the cloud leg of `glm`); a value already ending in `/chat/completions` is used verbatim |
| `GLM_CLOUD_MODEL` | `glm-5.3` | `glm-cloud` (e.g. `glm-5.3-flash` to trade quality for cost on the fallback) |
| `ZAI_API_KEY` / `ZAI_TOKEN` | — | cloud auth; `ZAI_TOKEN` is the alias slot from the 90-day plan. Optional for `glm-local` (a bare vLLM server ignores auth — no header is sent when no key is set) |

Keys can also arrive per-request through the standard BYOK factory
(`hyper_app/services/llm_factory.py`, `{"provider": "glm", "api_key": ..., "model": ...}`),
which takes precedence over the environment.

## Quickstart

```bash
# 1. Serve the weights locally (balanced tier, AWQ INT4 — verify flags
#    against the official model card before use).
vllm serve zai-org/GLM-5.3-AWQ --tensor-parallel-size 4 \
    --max-model-len 131072 --gpu-memory-utilization 0.92

# 2. Smoke-check the endpoint.
curl http://127.0.0.1:8000/v1/models

# 3. Use it from the platform.
#    BYOK request config: {"provider": "glm", ...}
#    Environment: GLM_LOCAL_URL + ZAI_API_KEY (cloud fallback only).
```

## Failover semantics (`glm`)

- Every call tries the **local server first** — zero egress cost, no data
  leaves the machine while it is healthy.
- Only when the local leg fails (connection refused, 5xx, malformed reply)
  does the request go to the cloud.
- The **next call starts from local again** — recovery is implicit and
  stateless, no health cache to go stale.
- Cloud-served replies carry `"failover": True`, and the connector keeps a
  `last_backend` attribute (`local` / `cloud` / `none`) so callers and the
  trace log can attribute each answer.
- If both legs fail, the reply is `{"ok": False, "error": "local: ...; cloud: ..."}`
  with the error text capped at 200 chars, like every other connector.

## Inference defaults

Both connectors send `temperature: 0.2` and `max_tokens: 8192` (coding-agent
settings from the 90-day plan); timeouts are 180 s local / 120 s cloud.

## Tests

`tests/test_glm_connectors.py` — 28 hermetic cases (no external network:
every HTTP case runs against a localhost mock server; all env touches go
through `monkeypatch`), covering endpoint/model resolution, key precedence,
payload shape, error mapping, failover both ways and factory integration.
The registered-provider contract in `tests/test_byok_integration.py` was
updated from six to nine providers.
