"""myGeeKy - find fellow GitHub geeks who are likely to follow you back.

myGeeKy never follows anyone automatically. It only ever suggests; you
decide who to follow, by hand, on github.com.
"""

__version__ = "0.19.0"


def use_system_certificates() -> None:
    """Trust the certificates this computer trusts (Windows/macOS/Linux store), not
    only Python's own list. Work networks that inspect secure connections
    (Zscaler, Netskope...) install their certificate in the computer's store, so
    without this every connection fails there while the browser works fine."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:   # Python 3.9, or not installed: Python's own list, as before
        pass
