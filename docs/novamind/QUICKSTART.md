# 🚀 NovaMind-Hive Quick Start

## Prerequisites
- Python 3.10+
- Git

## Installation
```bash
git clone <repo-url>
cd novamind-core
pip install -e .
```

## Running Locally
```bash
# Check status
python nova/cli/main.py status

# Run security scan
python nova/cli/main.py scan --security

# Launch Dashboard
cd web && python app.py
```

## Contributing
Please read `docs/CONTRIBUTING.md` before submitting PRs. Ensure `pre-commit` hooks pass locally.
