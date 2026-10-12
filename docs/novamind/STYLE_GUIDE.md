# Style guide — NovaMind documentation

> Reference: [Google Developer Documentation Style Guide](https://developers.google.com/style) and
> [Microsoft Writing Style Guide](https://learn.microsoft.com/en-us/style-guide).

## Headings

### Use sentence case

| ✅ Correct                    | ❌ Wrong                      |
| ----------------------------- | ----------------------------- |
| `Configure the agent factory` | `Configure The Agent Factory` |
| `Installation prerequisites`  | `Installation Prerequisites`  |

### Use action-oriented verbs for tasks

| ✅ Correct             | ❌ Wrong                |
| ---------------------- | ----------------------- |
| `Install the package`  | `Installation`          |
| `Configure logging`    | `Logging configuration` |
| `Deploy to production` | `Deployment`            |

### Use noun phrases for concepts

| ✅ Correct               | ❌ Wrong           |
| ------------------------ | ------------------ |
| `Authentication methods` | `Authenticate`     |
| `Agent registry design`  | `Designing agents` |

### Heading hierarchy

- **H1**: one per document, document title only
- **H2**: major sections
- **H3**: sub-sections
- **H4+**: rare, consider splitting the document instead

Never skip levels: `H1` → `H3` is **invalid**.

## Code examples

- Use fenced code blocks with language tag:
  ````markdown
  ```python
  from novamind.agents import factory
  ````
- Never include **real** secrets. Use placeholders:
  - `$API_KEY`
  - `${GEMINI_API_KEY}`
  - `<your-token-here>`
- Keep examples runnable. Test them in `examples/`.

## Security

### Never include:

- Real API keys (use `$ENV_VAR` placeholders)
- Internal hostnames or IPs
- Private repository URLs
- Personal email addresses

### Avoid prompt injection patterns:

- `Ignore all previous instructions`
- `You are now a ...`
- `Disregard the above`
- `Forget everything`

Vale will flag these automatically.

## Terminology

Use exact naming for NovaMind components:

| Term        | Not                        |
| ----------- | -------------------------- |
| `BaseAgent` | `base agent`, `base_agent` |
| `LLMRouter` | `llm_router`, `LLM Router` |
| `Commander` | `commander`                |
| `nova.yaml` | `nova.yml`, `NovaYAML`     |
| `NovaMind`  | `nova mind`, `nova-mind`   |

## Links

- Prefer **relative** links: `[architecture](./ARCHITECTURE.md)`
- Avoid **absolute** GitHub URLs in docs
- Check links with `make docs-links` (coming soon)

## Line length

Wrap at **100 characters** for readability.

## Automated enforcement

Run before commit:

```bash
mdformat docs/
vale docs/
pre-commit run --all-files
```

CI runs the same on every PR via `.github/workflows/docs-quality.yml`.

## When in doubt

Follow Google's guide. If still uncertain, ask in `#docs` Slack channel.
