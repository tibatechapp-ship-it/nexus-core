"""Fixtures مشتركة لجميع الاختبارات."""
import importlib
import inspect
import pytest


@pytest.fixture
def factory():
    from hive.factory import registry

    class Factory:
        REGISTRY = {}

        ALIASES = {
            "crypto": "crypto_agent", "xss": "xss_agent",
            "injection": "injection_agent", "secrets": "secrets_agent",
            "auth": "auth_agent", "dependency": "dependency_agent",
            "privacy": "privacy_agent", "compliance": "compliance_agent",
            "naming": "naming_agent", "complexity": "complexity_agent",
            "deadcode": "deadcode_agent", "duplication": "duplication_agent",
            "architecture": "architecture_agent", "api_design": "api_design_agent",
            "sql": "sql_agent", "nosql": "nosql_agent",
            "db_migration": "db_migration_agent", "orm": "orm_agent",
            "indexing": "indexing_agent", "transaction": "transaction_agent",
            "docker": "docker_agent", "k8s": "k8s_agent",
            "cicd": "cicd_agent", "nginx": "nginx_agent",
            "terraform": "terraform_agent", "monitoring": "monitoring_agent",
            "react": "react_agent", "vue": "vue_agent",
            "css": "css_agent", "a11y": "a11y_agent",
            "rtl": "rtl_agent", "prompt": "prompt_agent",
            "embedding": "embedding_agent", "finetune": "finetune_agent",
            "evaluation": "evaluation_agent", "builder": "agent_builder",
        }

        def __init__(self):
            self.REGISTRY = {}
            for name in registry.list_all():
                spec = registry.get(name)
                self.REGISTRY[name] = (spec.module, spec.class_name, spec.method)

        def list_all(self):
            return list(self.REGISTRY.keys())

        def list_available(self):
            available = []
            for name in self.REGISTRY:
                try:
                    self.get(name)
                    available.append(name)
                except Exception:
                    pass
            return available

        def _resolve(self, name):
            if name in self.REGISTRY:
                return name
            if name in self.ALIASES and self.ALIASES[name] in self.REGISTRY:
                return self.ALIASES[name]
            raise KeyError(f"Unknown agent: {name}")

        def get(self, name):
            resolved = self._resolve(name)
            module_path, class_name, _ = self.REGISTRY[resolved]
            mod = importlib.import_module(module_path)
            return getattr(mod, class_name)

        def call(self, name, **kwargs):
            try:
                resolved = self._resolve(name)
            except KeyError:
                return {"error": f"Unknown agent: {name}"}

            agent = self.get(name)
            _, _, method_name = self.REGISTRY[resolved]
            method = getattr(agent, method_name)
            sig = inspect.signature(method)
            params = list(sig.parameters.keys())

            attempts = [
                {"task": kwargs.get("code", ""), "ctx": kwargs},
                kwargs,
                {"code": kwargs.get("code", ""), "filename": kwargs.get("filename", "")},
            ]
            for attempt in attempts:
                filtered = {k: v for k, v in attempt.items() if k in params}
                if not filtered:
                    continue
                try:
                    result = method(**filtered)
                    if isinstance(result, dict):
                        return result
                    return {"result": result}
                except TypeError:
                    continue
            return {"result": None}

        def stats(self):
            cats = {}
            for spec in registry.specs.values():
                cats[spec.category] = cats.get(spec.category, 0) + 1
            total = len(self.REGISTRY)
            available = len(self.list_available())
            return {
                "total": total,
                "total_registered": total,
                "available": available,
                "failed": total - available,
                "errors": [],
                "categories": len(cats),
                "by_category": cats,
            }

        def get_agent_info(self, name):
            resolved = self._resolve(name)
            module_path, class_name, method = self.REGISTRY[resolved]
            return {"module": module_path, "class": class_name, "method": method}

    return Factory()


@pytest.fixture
def available_agent_names(factory):
    return factory.list_available()


@pytest.fixture
def expected_agent_count(factory):
    return len(factory.list_all())


@pytest.fixture
def sample_code():
    return "def hello():\n    password = 'hardcoded'\n    return 'world'\n\neval('dangerous')\n"


@pytest.fixture
def temp_project():
    import tempfile, shutil
    from pathlib import Path
    tmp_dir = Path(tempfile.mkdtemp())
    (tmp_dir / "nova").mkdir()
    (tmp_dir / "nova" / "__init__.py").touch()
    (tmp_dir / "tests").mkdir()
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)
