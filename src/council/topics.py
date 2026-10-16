"""مكتبة مواضيع المجلس."""
from typing import Any
from dataclasses import dataclass, field


@dataclass
class Topic:
    id: str
    category: str
    title: str
    question: str
    context: str = ""
    options: list = field(default_factory=list)
    risk_level: str = "low"


TOPICS = {
    "db_sqlite_vs_postgres": Topic("db_sqlite_vs_postgres", "database",
        "SQLite أم PostgreSQL؟",
        "هل نستخدم SQLite أم PostgreSQL لمشروعنا؟",
        "Termux/Android، موارد محدودة", ["SQLite", "PostgreSQL"]),
    "db_duckdb_vs_sqlite": Topic("db_duckdb_vs_sqlite", "database",
        "DuckDB أم SQLite؟",
        "أي أفضل للتحليلات: DuckDB أم SQLite؟",
        "تحليل بيانات، تقارير", ["DuckDB", "SQLite"]),
    "db_nosql_choice": Topic("db_nosql_choice", "database",
        "NoSQL أم SQL؟",
        "هل نحتاج NoSQL؟ MongoDB أم Redis أم لا؟",
        "تخزين مؤقت، جلسات", ["MongoDB", "Redis", "None"]),
    "fw_fastapi_vs_flask": Topic("fw_fastapi_vs_flask", "framework",
        "FastAPI أم Flask؟",
        "هل نستخدم FastAPI أم Flask؟",
        "API حديث، async", ["FastAPI", "Flask"]),
    "fw_django_vs_fastapi": Topic("fw_django_vs_fastapi", "framework",
        "Django أم FastAPI؟",
        "هل نستخدم Django أم FastAPI؟",
        "admin أم API خفيف؟", ["Django", "FastAPI"]),
    "fw_react_vs_vue": Topic("fw_react_vs_vue", "framework",
        "React أم Vue؟",
        "أي أفضل للواجهة؟",
        "تفاعلية، فريق صغير", ["React", "Vue"]),
    "llm_groq_vs_gemini": Topic("llm_groq_vs_gemini", "llm",
        "Groq أم Gemini؟",
        "أي أفضل: Groq أم Gemini؟",
        "سرعة، تكلفة، عربية", ["Groq", "Gemini"]),
    "llm_openrouter_vs_direct": Topic("llm_openrouter_vs_direct", "llm",
        "OpenRouter أم Direct؟",
        "OpenRouter أم اتصال مباشر؟",
        "مفاتيح متعددة", ["OpenRouter", "Direct"]),
    "llm_local_vs_cloud": Topic("llm_local_vs_cloud", "llm",
        "Ollama أم Cloud؟",
        "LLM محلي أم Cloud API؟",
        "خصوصية، تكلفة", ["Local", "Cloud"]),
    "sec_jwt_vs_session": Topic("sec_jwt_vs_session", "security",
        "JWT أم Session؟",
        "أي أفضل للمصادقة؟",
        "API، logout، revocation", ["JWT", "Session"], "high"),
    "sec_oauth_provider": Topic("sec_oauth_provider", "security",
        "أي OAuth؟",
        "Google, GitHub, أم مخصص؟",
        "تسجيل مستخدمين", ["Google", "GitHub", "Custom"], "high"),
    "sec_secrets_storage": Topic("sec_secrets_storage", "security",
        "أين نخزن المفاتيح؟",
        "أين نخزن secrets بأمان؟",
        "مفاتيح API، tokens", [".env", "Vault", "AWS"], "high"),
    "ops_docker_vs_podman": Topic("ops_docker_vs_podman", "devops",
        "Docker أم Podman؟",
        "أي أفضل: Docker أم Podman؟",
        "Android/Termux، أمان", ["Docker", "Podman"]),
    "ops_ci_choice": Topic("ops_ci_choice", "devops",
        "أي CI/CD؟",
        "GitHub Actions, GitLab CI, أم محلي؟",
        "مشروع صغير", ["GitHub", "GitLab", "Local"]),
    "arch_monolith_vs_micro": Topic("arch_monolith_vs_micro", "architecture",
        "Monolith أم Microservices؟",
        "أي معمارية نختار؟",
        "حجم الفريق", ["Monolith", "Microservices"]),
    "arch_rest_vs_graphql": Topic("arch_rest_vs_graphql", "architecture",
        "REST أم GraphQL؟",
        "أي أفضل للـ API؟",
        "عملاء متعددون", ["REST", "GraphQL"]),
    "perf_python_vs_rust": Topic("perf_python_vs_rust", "performance",
        "Python أم Rust؟",
        "للأداء الحرج: Python أم Rust؟",
        "سرعة، تعقيد", ["Python", "Rust"]),
    "perf_async_vs_sync": Topic("perf_async_vs_sync", "performance",
        "Async أم Sync؟",
        "async/await أم sync؟",
        "I/O كثيف", ["async", "sync"]),
    "ai_rag_vs_finetune": Topic("ai_rag_vs_finetune", "ai",
        "RAG أم Fine-tuning؟",
        "أيهما أفضل: RAG أم Fine-tuning؟",
        "معرفة حديثة، تكلفة", ["RAG", "Fine-tuning"]),
    "ai_embeddings_choice": Topic("ai_embeddings_choice", "ai",
        "أي embeddings؟",
        "hashing, ST, أم API؟",
        "جودة، سرعة", ["Hashing", "ST", "API"]),
    "nexus_agent_count": Topic("nexus_agent_count", "nexus",
        "كم وكيل نحتاج؟",
        "هل 79 وكيلاً كثير أم قليل؟",
        "النظام الحالي", ["Expand", "Keep", "Reduce"]),
    "nexus_router_strategy": Topic("nexus_router_strategy", "nexus",
        "Smart Router كافٍ؟",
        "هل استراتيجية Router كافية؟",
        "single/sequential/parallel/council", ["Keep", "Expand"]),
    "general_build_vs_buy": Topic("general_build_vs_buy", "general",
        "نبني أم نشتري؟",
        "نبني الحل أم نستخدم جاهز؟",
        "تكلفة، تحكم", ["Build", "Buy"]),
    "general_now_vs_later": Topic("general_now_vs_later", "general",
        "الآن أم لاحقاً؟",
        "ننفذ الآن أم نؤجل؟",
        "أولوية، قيمة", ["Now", "Later"]),
}


def get_topic(topic_id: Any) -> Any:
    return TOPICS.get(topic_id)


def list_categories() -> Any:
    r: dict[str, list] = {}
    for tid, t in TOPICS.items():
        r.setdefault(t.category, []).append({
            "id": tid, "title": t.title, "risk": t.risk_level
        })
    return r


def search_topics(query: Any) -> Any:
    q = query.lower()
    return [
        {"id": tid, "title": t.title, "category": t.category}
        for tid, t in TOPICS.items()
        if q in t.title.lower() or q in t.question.lower() or q in t.category.lower()
    ]
