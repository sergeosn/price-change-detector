"""Product page text for retrieval. Pure functions: no network, no database."""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from html import unescape

from bs4 import BeautifulSoup, Tag

from tracker.services.extractor import iter_json_ld_products

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
MAX_TITLE_LENGTH = 255  # ProductDocument.title
# Fewer "name: value" rows than this is not a specification.
MIN_SPECIFICATION_ROWS = 2
# A longer "name" is a sentence that happens to contain a colon, not a property name.
MAX_PROPERTY_NAME_LENGTH = 100

# Page chrome and code: never part of the product text.
_NOISE_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "svg",
    "iframe",
)
_WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class ExtractedContent:
    title: str  # '' when the page has none
    text: str  # '' when the page has no description and no specification


def extract_content(html: str) -> ExtractedContent:
    """Title and descriptive text of a product page.

    The text is the JSON-LD Product description, the meta description (unless it repeats
    the former) and "name: value" lines from JSON-LD additionalProperty and the main
    specification table or list, separated by blank lines. Navigation, headers, footers,
    scripts and other page chrome are left out.
    """
    soup = BeautifulSoup(html, "lxml")
    product = next(iter_json_ld_products(soup), {})
    meta_description = _meta(soup, name="description") or _meta(soup, property="og:description")
    page_title = _squash(soup.title.get_text()) if soup.title else ""
    fallback_titles = (_meta(soup, property="og:title"), page_title)
    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    heading = soup.find("h1")
    titles = (_plain(product.get("name")), _element_text(heading), *fallback_titles)
    title = next((candidate for candidate in titles if candidate), "")

    description = _plain(product.get("description"))
    sections = [description] if description else []
    if meta_description and not _repeats(meta_description, description):
        sections.append(meta_description)
    specification = _unique([*_json_ld_properties(product), *_main_specification(soup)])
    if specification:
        sections.append("\n".join(specification))
    return ExtractedContent(title=title[:MAX_TITLE_LENGTH].rstrip(), text="\n\n".join(sections))


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into chunks of at most `size` characters that share about `overlap`.

    Chunks start and end on word boundaries; a single word longer than `size` becomes a
    chunk of its own instead of being cut.
    """
    words = [match.span() for match in _WORD_RE.finditer(text)]
    chunks: list[str] = []
    first = 0
    while first < len(words):
        start = words[first][0]
        last = first
        while last + 1 < len(words) and words[last + 1][1] - start <= size:
            last += 1
        end = words[last][1]
        chunks.append(text[start:end])
        if last + 1 == len(words):
            break
        # The next chunk repeats the trailing words that fit into `overlap`, but always
        # starts after `first` so that every chunk moves forward.
        following = last + 1
        while following - 1 > first and end - words[following - 1][0] <= overlap:
            following -= 1
        first = following
    return chunks


# --- description and title -----------------------------------------------------------


def _meta(soup: BeautifulSoup, **attrs: str) -> str:
    tag = soup.find("meta", attrs=attrs)
    return _squash(tag.get("content") or "") if tag else ""


def _repeats(meta_description: str, description: str) -> bool:
    """Shops often put the (possibly truncated) start of the description into the meta tag."""
    return meta_description.rstrip(".… ").casefold() in description.casefold()


# --- specification -------------------------------------------------------------------


def _json_ld_properties(product: dict) -> Iterator[str]:
    properties = product.get("additionalProperty")
    if isinstance(properties, dict):
        properties = [properties]
    if not isinstance(properties, list):
        return
    for item in properties:
        if not isinstance(item, dict):
            continue
        name = _plain(item.get("name"))
        value = item.get("value")
        values = value if isinstance(value, list) else [value]
        value_text = ", ".join(filter(None, map(_plain, values)))
        if name and value_text:
            unit = _plain(item.get("unitText"))
            yield f"{name}: {value_text} {unit}".rstrip()


def _main_specification(soup: BeautifulSoup) -> list[str]:
    """Rows of the table or list with the most "name: value" pairs."""
    best: list[str] = []
    for element in soup.find_all(["table", "dl", "ul", "ol"]):
        rows = list(_specification_rows(element))
        if len(rows) > len(best):
            best = rows
    return best if len(best) >= MIN_SPECIFICATION_ROWS else []


def _specification_rows(element: Tag) -> Iterator[str]:
    for name, value in _name_value_pairs(element):
        name = name.rstrip(": ")
        if name and value and len(name) <= MAX_PROPERTY_NAME_LENGTH:
            yield f"{name}: {value}"


def _name_value_pairs(element: Tag) -> Iterator[tuple[str, str]]:
    if element.name == "table":
        for row in element.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if len(cells) == 2:
                yield _element_text(cells[0]), _element_text(cells[1])
    elif element.name == "dl":
        for term in element.find_all("dt"):
            yield _element_text(term), _element_text(term.find_next_sibling("dd"))
    else:
        for item in element.find_all("li", recursive=False):
            parts = item.find_all(True, recursive=False)
            if len(parts) == 2:
                yield _element_text(parts[0]), _element_text(parts[1])
            else:
                name, _, value = _element_text(item).partition(":")
                yield name, value.strip()


# --- helpers -------------------------------------------------------------------------


def _plain(value: object) -> str:
    """Plain single-line text of a scalar; '' for anything else. Markup is stripped."""
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return ""
    text = str(value)
    if "<" in text:
        return _squash(BeautifulSoup(text, "html.parser").get_text(" "))
    return _squash(unescape(text))


def _element_text(element: Tag | None) -> str:
    return _squash(element.get_text(" ")) if element is not None else ""


def _squash(text: str) -> str:
    """Collapse whitespace; drop NUL characters, which PostgreSQL text columns reject."""
    return " ".join(text.replace("\x00", "").split())


def _unique(lines: Iterable[str]) -> list[str]:
    """Drop repeated lines, ignoring case, keeping the first occurrence."""
    seen: set[str] = set()
    unique = []
    for line in lines:
        key = line.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(line)
    return unique
