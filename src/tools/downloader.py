"""Tool: download_file — uses aria2c with resume support for large files."""
import subprocess
import os
import ipaddress
from urllib.parse import urlparse

def _is_safe_url(url: str) -> bool:
    """Reject localhost, private IPs, and non-HTTP schemes (SSRF protection)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    
    hostname = parsed.hostname
    if not hostname:
        return False
        
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
        
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved:
            return False
    except ValueError:
        pass # Not an IP, it's a domain name (allowed)
        
    return True

def download_file(url: str, output_name: str | None = None, output_dir: str = ".") -> str:
    """Download a file using aria2c. Returns a status message."""
    if not _is_safe_url(url):
        raise ValueError("Unsafe URL blocked (SSRF protection)")
    
    base = os.path.abspath(output_dir)
    if not base.startswith(os.path.abspath(os.getcwd())):
        raise ValueError("output_dir must be within the project workspace")
    
    cmd = ["aria2c", "-c", "-x", "16", "-s", "16", "-d", base]
    if output_name:
        cmd.extend(["-o", output_name])
    cmd.append(url)
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    
    if result.returncode != 0:
        raise RuntimeError(f"aria2c failed: {result.stderr[-300:]}")
    
    return f"✅ Download complete: {output_name or url.split('/')[-1]}"
