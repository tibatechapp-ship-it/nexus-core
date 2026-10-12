#!/usr/bin/env python3
"""NovaMind — Live Agent Test"""
import warnings, asyncio, sys
warnings.filterwarnings('ignore')
# [FIXED PATH] Use relative imports or conftest.py instead

import novamind as nm

async def main():
    print("═══════════════════════════════════════════════")
    print("  Live Agent Test")
    print("═══════════════════════════════════════════════")
    print()

    # 1. OllamaProvider
    print("🤖 [1] OllamaProvider")
    try:
        ollama = nm.OllamaProvider()
        print(f"  ✅ Created")
        print(f"     Host: {getattr(ollama, 'host', getattr(ollama, 'base_url', 'N/A'))}")
    except Exception as e:
        print(f"  ⚠️  {e}")
    print()

    # 2. LLMRouter
    print("🤖 [2] LLMRouter")
    try:
        router = nm.LLMRouter()
        print(f"  ✅ Created")
        for attr in ["providers", "_providers", "provider_map"]:
            if hasattr(router, attr):
                print(f"     Providers: {len(getattr(router, attr))}")
                break
    except Exception as e:
        print(f"  ⚠️  {e}")
    print()

    # 3. CLIAgent
    print("🤖 [3] CLIAgent")
    try:
        cli = nm.CLIAgent()
        result = cli.verify_syntax("def hello():\n    return 'world'")
        print(f"  ✅ Syntax check: {result['status']}")
    except Exception as e:
        print(f"  ❌ {e}")
    print()

    # 4. GitAgent
    print("🤖 [4] GitAgent")
    try:
        git = nm.GitAgent()
        status = git.status()
        print(f"  ✅ Branch: {status.get('branch', 'N/A')}")
    except Exception as e:
        print(f"  ⚠️  {e}")
    print()

    # 5. AgentFactory
    print("🤖 [5] AgentFactory")
    try:
        factory = nm.AgentFactory()
        agents = factory.list_agents()
        print(f"  ✅ {len(agents)} agents: {', '.join(agents[:4])}...")
    except Exception as e:
        print(f"  ❌ {e}")
    print()

    # 6. Army Status
    print("🤖 [6] Army Summary")
    print(f"  📦 Dev Team:      {len(nm.DEV_TEAM)}")
    print(f"  ⚔️  Soldiers:      {len(nm.SOLDIERS)}")
    print(f"  🏭 Agent Prompts: {len(nm.AGENT_PROMPTS)}")
    print()

    # 7. Live LLM call (اختياري)
    print("🤖 [7] Live LLM Call (optional)")
    print("  ℹ️  Skipped — would consume tokens")
    print()

    print("═══════════════════════════════════════════════")
    print("  ✅ Test complete")
    print("═══════════════════════════════════════════════")

if __name__ == "__main__":
    asyncio.run(main())
