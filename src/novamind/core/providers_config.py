"""
تكوين المزودين المتاحين — النماذج المجانية فقط
═══════════════════════════════════════════════════════════════
هذا الملف يعرّف كل مزود ونماذجه المجانية.
يقرأه llm_router.py تلقائياً.
"""

PROVIDER_CONFIGS = {
    # ═══════════════════════════════════════════════════════════
    # Gemini — 21 مفتاح × نماذج مجانية ممتازة
    # ═══════════════════════════════════════════════════════════
    "gemini": {
        "pattern": "GEMINI_API_KEY",       # يبحث عن _1.._20
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "provider_type": "gemini",
        "priority_base": 10,
        "models": {
            "fast":  "gemini-3.8-flash",
            "smart": "gemini-3.8-flash",
            "mini":  "gemini-3.5-flash-lite",
        },
    },

    # ═══════════════════════════════════════════════════════════
    # Groq — 20 مفتاح × سرعة خارقة
    # ═══════════════════════════════════════════════════════════
    "groq": {
        "pattern": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "provider_type": "openai",
        "priority_base": 20,
        "models": {
            "fast":  "llama-3.1-8b-instant",
            "smart": "llama-3.3-70b-versatile",
            "mini":  "llama-3.2-1b-preview",
        },
    },

    # ═══════════════════════════════════════════════════════════
    # ZAI / GLM — 4 مفاتيح
    # ═══════════════════════════════════════════════════════════
    "zai_glm": {
        "pattern": "ZAI_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider_type": "openai",
        "priority_base": 40,
        "models": {
            "fast":  "glm-4-flash",
            "smart": "glm-4-plus",
            "mini":  "glm-4-flashx",
        },
    },

    # ═══════════════════════════════════════════════════════════
    # OpenRouter — 5 مفاتيح × نماذج :free
    # ═══════════════════════════════════════════════════════════
    "openrouter": {
        "pattern": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "provider_type": "openai",
        "priority_base": 50,
        "models": {
            "fast":  "meta-llama/llama-3.1-8b-instruct:free",
            "smart": "google/gemini-2.0-flash-exp:free",
            "mini":  "meta-llama/llama-3.2-3b-instruct:free",
        },
    },

    # ═══════════════════════════════════════════════════════════
    # Mistral — 9 مفاتيح × free tier
    # ═══════════════════════════════════════════════════════════
    "mistral": {
        "pattern": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "provider_type": "openai",
        "priority_base": 60,
        "models": {
            "fast":  "ministral-3b-latest",
            "smart": "mistral-small-latest",
            "mini":  "open-mistral-7b",
        },
    },

    # ═══════════════════════════════════════════════════════════
    # Ollama — محلي (احتياطي أخير)
    # ═══════════════════════════════════════════════════════════
    "ollama": {
        "pattern": "OLLAMA_HOST",
        "base_url": "http://localhost:11434/v1",
        "provider_type": "openai",
        "priority_base": 90,
        "models": {
            "fast":  "llama3.2:3b",
            "smart": "qwen2.5:7b",
            "mini":  "llama3.2:1b",
        },
    },
}
