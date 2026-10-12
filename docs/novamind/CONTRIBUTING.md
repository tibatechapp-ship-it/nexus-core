# المساهمة في NovaMind

## قبل البدء

- Python 3.11+
- git, pytest

## سير العمل

## متطلبات PR

- الاختبارات: 100/100
- nova.\_registry.validate() = صفر أخطاء
- CHANGELOG.md محدّث
- لا secrets

## إضافة وكيل جديد

1. أنشئ nova/agents/my_agent.py
2. سجّله في nova/registry_v2.py
3. python3 nova/scripts/build_nova_yaml.py
4. pytest tests/unit/test_agent_contract.py -v

## معايير الكود

- PEP 8
- Type hints
- Docstrings للدوال العامة
- Line length ≤ 100
