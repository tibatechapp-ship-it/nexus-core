"""Web tools - fetch URLs, HTTP POST, search, extract"""
from pathlib import Path
import sys
import json
import re
import html
import urllib.request
import urllib.parse
import urllib.error
import ssl
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.base import Tool, ToolResult, registry


# ═══════════════════════════════════════════════════════
#  Helper: HTML text extraction
# ═══════════════════════════════════════════════════════
def extract_text_from_html(raw_html: str) -> str:
    """Strip HTML tags, scripts, styles and return clean text."""
    if not raw_html:
        return ""

    text = raw_html

    # Remove <script>...</script>
    text = re.sub(r'<script[^>]*>.*?</script>',
                  '', text, flags=re.DOTALL | re.IGNORECASE)
    # Remove <style>...</style>
    text = re.sub(r'<style[^>]*>.*?</style>',
                  '', text, flags=re.DOTALL | re.IGNORECASE)
    # Remove <noscript>...</noscript>
    text = re.sub(r'<noscript[^>]*>.*?</noscript>',
                  '', text, flags=re.DOTALL | re.IGNORECASE)
    # Remove comments
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

    # Convert block tags to newlines
    text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</(p|div|h[1-6]|li|tr|section|article)>',
                  '\n', text, flags=re.IGNORECASE)

    # Remove all remaining tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode HTML entities
    text = html.unescape(text)

    # Collapse multiple newlines
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    # Collapse spaces
    text = re.sub(r'[ \t]+', ' ', text)

    # Trim lines
    lines = [line.strip() for line in text.split('\n')]
    lines = [l for l in lines if l]

    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════
#  1. FetchURLTool (existing, improved)
# ═══════════════════════════════════════════════════════
class FetchURLTool(Tool):
    name = "fetch_url"
    description = "Fetch the content of a URL (HTTP GET)."
    danger_level = "warn"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 100000},
                "timeout": {"type": "integer", "default": 15},
            },
            "required": ["url"],
        }

    def run(self, url, max_bytes=100000, timeout=15):
        if not url.startswith(("http://", "https://")):
            return ToolResult(ok=False, error="invalid URL")

        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (NovaMind/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                content = resp.read(max_bytes)
                charset = resp.headers.get_content_charset() or "utf-8"
                try:
                    text = content.decode(charset, errors="replace")
                except Exception:
                    text = content.decode("utf-8", errors="replace")

                return ToolResult(ok=True, data={
                    "url": url,
                    "status": resp.status,
                    "content_type": resp.headers.get("Content-Type", ""),
                    "size": len(content),
                    "text": text,
                })
        except urllib.error.HTTPError as e:
            return ToolResult(ok=False, error="HTTP " + str(e.code))
        except urllib.error.URLError as e:
            return ToolResult(ok=False, error="URL: " + str(e.reason)[:100])
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


# ═══════════════════════════════════════════════════════
#  2. HTTPPostTool (existing)
# ═══════════════════════════════════════════════════════
class HTTPPostTool(Tool):
    name = "http_post"
    description = "Send HTTP POST with JSON body."
    danger_level = "warn"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "json_body": {"type": "object"},
                "timeout": {"type": "integer", "default": 15},
            },
            "required": ["url", "json_body"],
        }

    def run(self, url, json_body, timeout=15):
        if not url.startswith(("http://", "https://")):
            return ToolResult(ok=False, error="invalid URL")

        try:
            data = json.dumps(json_body).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json",
                         "User-Agent": "NovaMind/1.0"},
                method="POST",
            )
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                body = resp.read(100000).decode("utf-8", errors="replace")
                return ToolResult(ok=True, data={
                    "url": url, "status": resp.status,
                    "response": body[:5000],
                })
        except urllib.error.HTTPError as e:
            return ToolResult(ok=False, error="HTTP " + str(e.code))
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


# ═══════════════════════════════════════════════════════
#  3. ExtractTextTool (NEW)
# ═══════════════════════════════════════════════════════
class ExtractTextTool(Tool):
    name = "extract_text"
    description = "Extract clean readable text from raw HTML."
    danger_level = "safe"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "html": {"type": "string"},
                "max_chars": {"type": "integer", "default": 8000},
            },
            "required": ["html"],
        }

    def run(self, html_content, max_chars=8000):
        try:
            text = extract_text_from_html(html_content)
            truncated = False
            if len(text) > max_chars:
                text = text[:max_chars]
                truncated = True
            return ToolResult(ok=True, data={
                "text": text,
                "length": len(text),
                "truncated": truncated,
            })
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


# ═══════════════════════════════════════════════════════
#  4. SmartFetchTool (NEW) - fetch + extract in one
# ═══════════════════════════════════════════════════════
class SmartFetchTool(Tool):
    name = "smart_fetch"
    description = "Fetch URL and return clean readable text automatically."
    danger_level = "warn"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "default": 8000},
                "timeout": {"type": "integer", "default": 15},
            },
            "required": ["url"],
        }

    def run(self, url, max_chars=8000, timeout=15):
        if not url.startswith(("http://", "https://")):
            return ToolResult(ok=False, error="invalid URL")

        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (NovaMind/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read(200000)
                charset = resp.headers.get_content_charset() or "utf-8"
                try:
                    content = raw.decode(charset, errors="replace")
                except Exception:
                    content = raw.decode("utf-8", errors="replace")

                content_type = resp.headers.get("Content-Type", "")

                # If JSON, return as-is
                if "json" in content_type.lower():
                    return ToolResult(ok=True, data={
                        "url": url,
                        "type": "json",
                        "text": content[:max_chars],
                        "truncated": len(content) > max_chars,
                    })

                # Else extract text
                text = extract_text_from_html(content)
                truncated = len(text) > max_chars
                if truncated:
                    text = text[:max_chars]

                return ToolResult(ok=True, data={
                    "url": url,
                    "type": "html",
                    "status": resp.status,
                    "text": text,
                    "length": len(text),
                    "truncated": truncated,
                })
        except urllib.error.HTTPError as e:
            return ToolResult(ok=False, error="HTTP " + str(e.code))
        except urllib.error.URLError as e:
            return ToolResult(ok=False, error="URL: " + str(e.reason)[:100])
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


# ═══════════════════════════════════════════════════════
#  5. WebSearchTool (NEW) - DuckDuckGo HTML
# ═══════════════════════════════════════════════════════
class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web using DuckDuckGo HTML API (no API key)."
    danger_level = "safe"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "num_results": {"type": "integer", "default": 5},
                "timeout": {"type": "integer", "default": 15},
            },
            "required": ["query"],
        }

    def run(self, query, num_results=5, timeout=15):
        if not query or not query.strip():
            return ToolResult(ok=False, error="empty query")

        try:
            # DuckDuckGo HTML endpoint (no API key needed)
            base_url = "https://html.duckduckgo.com/html/"
            params = {"q": query}
            url = base_url + "?" + urllib.parse.urlencode(params)

            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (NovaMind/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read(300000).decode("utf-8", errors="replace")

            # Parse DDG HTML results
            # Each result has: <a class="result__a" href="...">Title</a>
            # And snippet: <a class="result__snippet">...</a>
            results = []

            # Find all result blocks
            result_pattern = re.compile(
                r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
                r'.*?(?:<a[^>]*class="result__snippet"[^>]*>(.*?)</a>)?',
                re.DOTALL | re.IGNORECASE
            )

            for match in result_pattern.finditer(raw):
                href = match.group(1)
                title = extract_text_from_html(match.group(2))
                snippet = extract_text_from_html(match.group(3) or "")

                # Decode DDG redirect URL
                if "uddg=" in href:
                    try:
                        parsed = urllib.parse.urlparse(href)
                        qs = urllib.parse.parse_qs(parsed.query)
                        if "uddg" in qs:
                            href = qs["uddg"][0]
                    except Exception:
                        pass

                if title and href:
                    results.append({
                        "title": title[:200],
                        "url": href,
                        "snippet": snippet[:300],
                    })

                if len(results) >= num_results:
                    break

            return ToolResult(ok=True, data={
                "query": query,
                "results": results,
                "count": len(results),
            })
        except urllib.error.HTTPError as e:
            return ToolResult(ok=False, error="HTTP " + str(e.code))
        except urllib.error.URLError as e:
            return ToolResult(ok=False, error="URL: " + str(e.reason)[:100])
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


# ═══════════════════════════════════════════════════════
#  Register all
# ═══════════════════════════════════════════════════════
registry.register(FetchURLTool())
registry.register(HTTPPostTool())
registry.register(ExtractTextTool())
registry.register(SmartFetchTool())
registry.register(WebSearchTool())
