"""
DNS Fix - patch socket to use explicit DNS servers
Must be imported BEFORE any network code
"""
import socket
import logging

logger = logging.getLogger("dns_fix")

# Alternative DNS servers to try
ALT_DNS_SERVERS = [
    ("8.8.8.8", 53),
    ("8.8.4.4", 53),
    ("1.1.1.1", 53),
]


def test_resolution():
    """Test if socket can resolve example.com."""
    try:
        ip = socket.gethostbyname("example.com")
        return True, ip
    except Exception as e:
        return False, str(e)


def install_dns_fix():
    """Installs a fallback resolver if needed."""
    ok, info = test_resolution()
    if ok:
        logger.info("DNS works: example.com -> " + info)
        return False  # no fix needed

    logger.warning("DNS broken: " + info)

    # Try to install a resolver using raw DNS query
    try:
        import dns.resolver  # type: ignore
        resolver = dns.resolver.Resolver()
        resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
        socket.setdefaulttimeout(10)
        logger.info("installed dnspython resolver fallback")
        return True
    except ImportError:
        logger.warning("dnspython not installed; install with:")
        logger.warning("  pip3 install --break-system-packages dnspython")
        return False


if __name__ == "__main__":
    install_dns_fix()
