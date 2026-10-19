import os
import json
import urllib.request
import urllib.error

def call_ollama(prompt: str, model: str = "gemma4:31b") -> str:
    """Sends a chat request to Ollama Cloud and returns the response."""
    api_key = os.environ.get("OLLAMA_API_KEY")
    if not api_key:
        raise ValueError("OLLAMA_API_KEY is not set in the environment.")

    url = "https://ollama.com/api/chat"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result.get("message", {}).get("content", "")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return "Error: 401 Unauthorized (The API key is wrong or missing)"
        elif e.code == 402:
            return "Error: 402 Payment Required (The model is not in your plan)"
        elif e.code == 404:
            return "Error: 404 Not Found (The model name is wrong)"
        elif e.code == 429:
            return "Error: 429 Too Many Requests (Usage limit reached)"
        else:
            return f"Error: HTTP {e.code} - {e.reason}"
    except urllib.error.URLError as e:
        return f"Error: Could not connect to Ollama - {e.reason}"
    except Exception as e:
        return f"Error: {str(e)}"
