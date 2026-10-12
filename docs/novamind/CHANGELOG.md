# سجل التغييرات

جميع التغييرات الملحوظة توثّق هنا. مبني على Keep a Changelog. يتبع Semantic Versioning.

## [Unreleased]

### Added

- (سيُملأ لاحقاً)

## [2.0.0] — 2026-10-09

### Added

- nova/\_registry/ — مصدر حقيقة موحد (79 وكيل)
- nova/\_registry/data/nova.yaml (1271 سطر)
- nova/scripts/build_nova_yaml.py — مولّد
- nova/commander.py — القيادة الواحدة
- 52 aliases — crypto ↔ crypto_agent
- Roles: 53 tool + 26 manager
- .github/workflows/agents-code-review.yml

### Changed

- nova/agents/factory.py — يقرأ من nova.\_registry
- nova/registry_v2.py — shim (708 → 110 سطر)
- tests/conftest.py — fixtures من المصدر
- tests/unit/test_agent_contract.py — 7 اختبارات

### Fixed

- 52 → 79 وكيل — وكلاء ضائعون
- 3 fixtures مفقودة
- 4 اختبارات قديمة

### Removed

- skip_agents
- 80% threshold
- تكرار في registry_v2.py

### Stats

- Before: 96/100 اختبارات، 52 وكيل، 3 مصادر
- After: 100/100 اختبارات، 79 وكيل، 1 مصدر
