"""
MCP Server — Expose NovaMind's 52 agents as MCP tools.

MCP (Model Context Protocol) is the 2026 standard for connecting
AI agents to tools and data sources.

Usage:
    # stdio transport (for Claude Desktop, Cursor, etc.)
    python -m core.mcp_server

    # Or programmatically:
    from novamind.core.mcp_server import NovaMindMCP
    mcp = NovaMindMCP()
    tools = mcp.list_tools()
    result = mcp.call_tool("crypto", {"code": "..."})

Protocol: JSON-RPC 2.0 over stdio.
"""
import sys
import json
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("core.mcp_server")


# ═══════════════════════════════════════════════════════════
# MCP Protocol Constants
# ═══════════════════════════════════════════════════════════
MCP_VERSION = "2024-11-05"
SERVER_NAME = "novamind"
SERVER_VERSION = "8.0.0"


# ═══════════════════════════════════════════════════════════
# NovaMind MCP Server
# ═══════════════════════════════════════════════════════════
class NovaMindMCP:
    """
    MCP-compliant server exposing NovaMind agents as tools.

    Each agent becomes an MCP tool with:
    - name: agent name (e.g., "crypto")
    - description: what the agent does
    - inputSchema: JSON Schema for the arguments
    """

    # Agent category descriptions (for MCP tool descriptions)
    CATEGORIES = {
        "analyzer": "Static analysis of Python code",
        "arabic": "Arabic language code analysis",
        "coder": "Generate Python code from description",
        "fixer": "Fix Python code errors",
        "multi_fixer": "Multi-strategy code fixing",
        "git": "Git operations via natural language",
        "learner": "Learn from past mistakes",
        "test_generator": "Generate unit tests",
        "test_runner": "Run pytest and report results",
        "tester": "Safely execute Python code",
        "security": "General security analysis",
        "performance": "Performance analysis",
        "documentation": "Documentation quality check",
        "refactor": "Code refactoring suggestions",
        "code_review": "Code review",
        "migration": "Migration analysis (Py2→Py3, etc.)",
        "crypto": "Detect weak cryptography",
        "injection": "Detect SQL/NoSQL/Command injection",
        "xss": "Detect XSS/CSRF vulnerabilities",
        "auth": "Authentication flow analysis",
        "dependency": "Dependency vulnerability check",
        "secrets": "Detect hardcoded secrets",
        "privacy": "PII/GDPR compliance",
        "compliance": "SOC2/ISO/HIPAA compliance",
        "naming": "Naming convention analysis",
        "complexity": "Cyclomatic complexity",
        "deadcode": "Detect unused code",
        "duplication": "Detect DRY violations",
        "architecture": "Architecture/SOLID analysis",
        "api_design": "REST/GraphQL API design",
        "sql": "SQL anti-patterns",
        "nosql": "NoSQL patterns",
        "db_migration": "Database migration safety",
        "orm": "ORM usage analysis",
        "indexing": "Missing indexes",
        "transaction": "ACID/isolation issues",
        "docker": "Dockerfile optimization",
        "k8s": "Kubernetes manifests",
        "cicd": "CI/CD pipeline analysis",
        "nginx": "Nginx config analysis",
        "terraform": "Terraform IaC analysis",
        "monitoring": "Observability analysis",
        "react": "React patterns",
        "vue": "Vue patterns",
        "css": "CSS/Tailwind analysis",
        "a11y": "Accessibility (WCAG)",
        "rtl": "RTL/Arabic UI",
        "prompt": "Prompt engineering analysis",
        "embedding": "Vector search analysis",
        "finetune": "Fine-tuning data analysis",
        "evaluation": "LLM evaluation",
        "builder": "Agent builder (meta)",
    }

    # Default input schema
    DEFAULT_SCHEMA = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to analyze",
            },
            "filename": {
                "type": "string",
                "description": "Optional filename for context",
                "default": "code.py",
            },
        },
        "required": ["code"],
    }

    def __init__(self, factory=None):
        self._factory = factory
        self._initialized = False

    @property
    def factory(self):
        if self._factory is None:
            from novamind.agents.factory import AgentFactory
            self._factory = AgentFactory()
        return self._factory

    # ═══════════════════════════════════════════════════════
    # MCP Protocol Methods
    # ═══════════════════════════════════════════════════════

    def initialize(self, params: Dict) -> Dict:
        """MCP initialize handshake."""
        self._initialized = True
        return {
            "protocolVersion": MCP_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        }

    def list_tools(self) -> Dict:
        """MCP tools/list — return all 52 agents as tools."""
        tools = []
        for name in sorted(self.factory.list_all()):
            description = self.CATEGORIES.get(name, f"NovaMind agent: {name}")
            tools.append({
                "name": name,
                "description": f"[NovaMind] {description}",
                "inputSchema": self.DEFAULT_SCHEMA,
            })
        return {"tools": tools}

    def call_tool(self, name: str, arguments: Dict) -> Dict:
        """MCP tools/call — execute an agent."""
        if name not in self.factory.list_all():
            return self._error_content(f"Unknown tool: {name}")

        # Special handling for agents that don't take 'code'
        code = arguments.get("code", "")
        filename = arguments.get("filename", "code.py")

        try:
            result = self.factory.call(name, code=code, filename=filename)
        except TypeError:
            # Some agents don't accept filename
            try:
                result = self.factory.call(name, code=code)
            except Exception as e:
                return self._error_content(f"{type(e).__name__}: {e}")
        except Exception as e:
            return self._error_content(f"{type(e).__name__}: {e}")

        return self._text_content(json.dumps(result, indent=2, ensure_ascii=False))

    def ping(self) -> Dict:
        """MCP ping."""
        return {}

    # ═══════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════

    def _text_content(self, text: str) -> Dict:
        return {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }

    def _error_content(self, error: str) -> Dict:
        return {
            "content": [{"type": "text", "text": f"Error: {error}"}],
            "isError": True,
        }

    # ═══════════════════════════════════════════════════════
    # JSON-RPC Dispatcher
    # ═══════════════════════════════════════════════════════

    def handle_request(self, request: Dict) -> Optional[Dict]:
        """Handle a JSON-RPC 2.0 request. Returns None for notifications."""
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        # Notifications have no id
        is_notification = req_id is None

        try:
            if method == "initialize":
                result = self.initialize(params)
            elif method == "notifications/initialized":
                return None  # notification
            elif method == "tools/list":
                result = self.list_tools()
            elif method == "tools/call":
                result = self.call_tool(
                    params.get("name", ""),
                    params.get("arguments", {}),
                )
            elif method == "ping":
                result = self.ping()
            else:
                if is_notification:
                    return None
                return self._jsonrpc_error(req_id, -32601, f"Method not found: {method}")

            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        except Exception as e:
            logger.exception("MCP handler error")
            if is_notification:
                return None
            return self._jsonrpc_error(req_id, -32603, str(e))

    def _jsonrpc_error(self, req_id: Any, code: int, message: str) -> Dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }


# ═══════════════════════════════════════════════════════════
# stdio transport
# ═══════════════════════════════════════════════════════════

def run_stdio_server():
    """Run MCP server over stdio (for Claude Desktop, Cursor, etc.)."""
    mcp = NovaMindMCP()
    logger.info("MCP server ready (52 agents)")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning(f"invalid JSON: {e}")
            continue

        response = mcp.handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════
mcp_server = NovaMindMCP()


__all__ = ["NovaMindMCP", "mcp_server", "run_stdio_server", "MCP_VERSION"]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    run_stdio_server()
