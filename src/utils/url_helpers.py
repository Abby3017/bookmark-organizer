import hashlib
from urllib.parse import urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    """Normalize a URL before generating its stable identifier."""
    parts = urlsplit(url.strip())

    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/"),
        parts.query,
        "",  # Ignore fragments
    ))


def bookmark_id(url: str) -> str:
    """Return a stable, compact identifier for a bookmark URL."""
    normalized = normalize_url(url)
    # for current use case, we can use a truncated SHA256 hash of the normalized URL
    # however for full implementation, we might want to consider a more sophisticated approach to avoid collisions
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return digest