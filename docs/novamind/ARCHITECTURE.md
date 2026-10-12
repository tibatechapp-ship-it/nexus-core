# معمارية NovaMind

## نظرة عامة

NovaMind = نظام وكلاء ذكي موحّد بمصدر حقيقة واحد.

Commander → nova.\_registry → factory → agents

## البنية

- nova/\_registry/ — المصدر الوحيد
- nova/agents/factory.py — يقرأ من \_registry
- nova/commander.py — القيادة
- nova/registry_v2.py — shim
- hive/factory/pipeline.py — 4 pipelines

## المكونات

### nova.\_registry

- المصدر الوحيد للحقيقة
- agent(name), all_agent_names(), validate()
- aliases تلقائية

### nova.agents.factory

- يقرأ REGISTRY من \_registry
- يضمن .name على كل وكيل
- يحترم role: tool vs manager

### nova.commander

- execute(task, pipeline)
- choose_pipeline(task) — rule-based
- History + stats

## الإحصاءات

- Agents: 79
- Aliases: 52
- Tools: 53
- Managers: 26
- Pipelines: 4
- Categories: 8
- Criticalities: 3
- Providers: 6
