"""Domain normalisation shared by Product and DomainRule."""

from urllib.parse import urlsplit


def normalize_domain(value: str) -> str:
    """Return the lowercase host of a domain or URL without 'www.', port and path.

    Returns an empty string when the value has no usable host.
    """
    value = value.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"//{value}"
    try:
        host = urlsplit(value).hostname or ""
    except ValueError:
        return ""
    host = host.rstrip(".")
    if any(char.isspace() for char in host):
        return ""
    return host.removeprefix("www.")
