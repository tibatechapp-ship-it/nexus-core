import configparser
from pathlib import Path


def test_novamind_coverage_config_measures_the_package_not_framework_exclusions():
    root = Path(__file__).resolve().parents[3]
    config = configparser.ConfigParser()
    config_path = root / "coverage-novamind.ini"

    assert config_path.is_file()
    config.read(config_path, encoding="utf-8")

    assert config.get("run", "source").strip() == "novamind"
    omitted = config.get("run", "omit")
    assert "*/tests/*" in omitted
    assert "src/novamind/*" not in omitted
