import json

import pytest

from tests.helpers import load_fixture
from tracker.services.content import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    ExtractedContent,
    chunk_text,
    extract_content,
)

UK_SPECS = (
    "Тип жорен: Плоскі сталеві\n"
    "Діаметр жорен: 50 мм\n"
    "Потужність: 166 Вт\n"
    "Місткість бункера: 300 г\n"
    "Вага: 7 кг\n"
    "Країна виробництва: Італія"
)
EN_TEXT = (
    "A two-person, three-season tent for backpacking & bikepacking. "
    "Two doors and two vestibules keep wet gear outside.\n\n"
    "Free shipping on the Northpeak Trailhead 2 backpacking tent. "
    "In stock and ready to ship.\n\n"
    "Capacity: 2 people\n"
    "Packed weight: 1.4 kg\n"
    "Floor area: 2.7 m²\n"
    "Seasons: 3-season"
)


def page(body: str = "", head: str = "") -> str:
    return f"<html><head>{head}</head><body>{body}</body></html>"


def product_jsonld(**fields) -> str:
    data = {"@context": "https://schema.org", "@type": "Product", **fields}
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


# --- extract_content: fixtures -----------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "title"),
    [
        ("jsonld_offer.html", "Apple iPhone 15 128GB"),
        ("jsonld_graph.html", "Graph product"),
        ("jsonld_offers_list.html", "Kindle Paperwhite"),
        ("jsonld_aggregate.html", "Aggregate product"),
        ("jsonld_broken.html", "Valid after broken"),
        ("microdata.html", "Coffee grinder"),
        ("opengraph.html", "OG product"),
        ("priority.html", "Priority product"),
        ("selector_only.html", "Selector product"),
        ("no_price.html", "Nothing here"),
    ],
)
def test_pages_without_description_or_specifications_give_a_title_and_no_text(fixture, title):
    assert extract_content(load_fixture(fixture)) == ExtractedContent(title=title, text="")


def test_ukrainian_page():
    content = extract_content(load_fixture("content_uk.html"))

    assert content.title == "Кавомолка Arabella G55"
    description, specifications = content.text.split("\n\n")
    assert description.startswith("Жорнова кавомолка Arabella G55 з 55 ступенями помелу")
    assert description.endswith("Гарантія виробника становить два роки.")
    assert specifications == UK_SPECS
    # The meta description repeats the first sentence of the description: kept once.
    assert content.text.count("з 55 ступенями помелу для еспресо та фільтр-кави") == 1


def test_english_page():
    assert extract_content(load_fixture("content_en.html")) == ExtractedContent(
        title="Northpeak Trailhead 2 Tent", text=EN_TEXT
    )


@pytest.mark.parametrize(
    ("fixture", "noise"),
    [
        ("content_uk.html", "Головна"),  # navigation
        ("content_uk.html", "Контакти"),  # navigation list that looks like "name: value"
        ("content_uk.html", "Безкоштовна доставка"),  # header
        ("content_uk.html", "dataLayer"),  # script
        ("content_uk.html", "стилі сторінки"),  # style
        ("content_uk.html", "темперу"),  # aside
        ("content_uk.html", "Нова Пошта"),  # footer table, longer than the specifications
        ("content_uk.html", "Усі права захищено"),  # footer
        ("content_uk.html", "Колір"),  # a smaller table in the main content
        ("content_uk.html", "Основні"),  # heading row of the specification table
        ("content_en.html", "Packs"),  # navigation
        ("content_en.html", "Summer sale"),  # header
        ("content_en.html", "analytics"),  # script
        ("content_en.html", "JavaScript"),  # noscript
        ("content_en.html", "Newsletter"),  # form
        ("content_en.html", "Phone"),  # footer list, longer than the specifications
        ("content_en.html", "Express"),  # a smaller table in the main content
        ("content_en.html", "Outdoor gear shop"),  # description of a non-Product node
    ],
)
def test_page_chrome_is_left_out(fixture, noise):
    assert noise not in extract_content(load_fixture(fixture)).text


# --- extract_content: title ----------------------------------------------------------


def test_title_prefers_json_ld_name():
    html = page(
        "<h1>Heading</h1>",
        "<title>Page title</title>"
        '<meta property="og:title" content="OG title">' + product_jsonld(name="  JSON-LD\n name "),
    )
    assert extract_content(html).title == "JSON-LD name"


def test_title_falls_back_to_heading_then_opengraph_then_title_tag():
    head = '<title>Page title</title><meta property="og:title" content="OG title">'
    assert extract_content(page("<h1>Main <b>heading</b></h1>", head)).title == "Main heading"
    assert extract_content(page("<header><h1>Shop logo</h1></header>", head)).title == "OG title"
    assert extract_content(page("", "<title>Page title</title>")).title == "Page title"


def test_title_is_empty_when_the_page_has_none_and_is_cut_to_the_column_length():
    assert extract_content("") == ExtractedContent(title="", text="")
    assert len(extract_content(page("<h1>" + "x" * 300 + "</h1>")).title) == 255


# --- extract_content: description ----------------------------------------------------


def test_meta_description_alone_is_the_text():
    html = page(head='<meta name="description" content="  A sturdy\n kettle. ">')
    assert extract_content(html).text == "A sturdy kettle."


def test_opengraph_description_is_used_when_there_is_no_meta_description():
    html = page(head='<meta property="og:description" content="OG text">')
    assert extract_content(html).text == "OG text"


def test_meta_description_that_differs_from_the_description_is_added_after_it():
    html = page(
        head='<meta name="description" content="Buy now.">' + product_jsonld(description="Long.")
    )
    assert extract_content(html).text == "Long.\n\nBuy now."


@pytest.mark.parametrize("meta", ["A sturdy kettle", "a sturdy kettle...", "A sturdy kettle…"])
def test_meta_description_repeating_the_description_is_dropped(meta):
    html = page(
        head=f'<meta name="description" content="{meta}">'
        + product_jsonld(description="A sturdy kettle. Boils fast.")
    )
    assert extract_content(html).text == "A sturdy kettle. Boils fast."


def test_description_markup_and_entities_become_plain_text():
    markup = product_jsonld(description="<ul><li>Fast</li><li>Quiet &amp; light</li></ul>")
    entities = product_jsonld(description="Salt &amp; pepper\u0000 mill")
    assert extract_content(page(head=markup)).text == "Fast Quiet & light"
    assert extract_content(page(head=entities)).text == "Salt & pepper mill"


@pytest.mark.parametrize("description", [None, True, ["a", "b"], {"@value": "x"}, "   "])
def test_unusable_description_is_ignored(description):
    assert extract_content(page(head=product_jsonld(description=description))).text == ""


# --- extract_content: specifications -------------------------------------------------


def test_json_ld_properties_become_name_value_lines():
    properties = [
        {"@type": "PropertyValue", "name": "Colour", "value": "Black"},
        {"name": "Weight", "value": 1.5, "unitText": "kg"},
        {"name": "Ports", "value": ["USB-C", "HDMI"]},
        {"name": "Waterproof", "value": True},
        {"name": "", "value": "nameless"},
        {"name": "Empty", "value": ""},
        "not a property",
    ]
    html = page(head=product_jsonld(additionalProperty=properties))
    assert extract_content(html).text == "Colour: Black\nWeight: 1.5 kg\nPorts: USB-C, HDMI"


def test_single_json_ld_property_and_malformed_properties():
    single = product_jsonld(additionalProperty={"name": "Colour", "value": "Black"})
    malformed = product_jsonld(additionalProperty="Colour: Black")
    assert extract_content(page(head=single)).text == "Colour: Black"
    assert extract_content(page(head=malformed)).text == ""


def test_definition_list_specifications():
    body = (
        "<dl><div><dt>Volume:</dt><dd>1.7 l</dd></div>"
        "<div><dt>Power</dt><dd>2200 W</dd></div><dt>Orphan</dt></dl>"
    )
    assert extract_content(page(body)).text == "Volume: 1.7 l\nPower: 2200 W"


def test_bullet_list_specifications():
    body = (
        "<ul><li>Volume: 1.7 l</li><li><span>Power</span><span>2200 W</span></li>"
        "<li>Just a sentence</li><li>: no name</li></ul>"
    )
    assert extract_content(page(body)).text == "Volume: 1.7 l\nPower: 2200 W"


def test_the_largest_candidate_is_the_main_specification():
    body = (
        "<ul><li>A: 1</li><li>B: 2</li></ul>"
        "<table><tr><td>C</td><td>3</td></tr><tr><td>D</td><td>4</td></tr>"
        "<tr><td>E</td><td>5</td></tr></table>"
    )
    assert extract_content(page(body)).text == "C: 3\nD: 4\nE: 5"


def test_a_single_pair_or_long_prose_is_not_a_specification():
    one_row = "<table><tr><td>Colour</td><td>Black</td></tr></table>"
    prose = "<ul><li>{0}: a</li><li>{0}: b</li></ul>".format("word " * 30)
    assert extract_content(page(one_row)).text == ""
    assert extract_content(page(prose)).text == ""


def test_table_rows_repeating_json_ld_properties_are_kept_once():
    html = page(
        "<table><tr><th>Colour</th><td>black</td></tr><tr><th>Size</th><td>M</td></tr></table>",
        product_jsonld(additionalProperty=[{"name": "Colour", "value": "Black"}]),
    )
    assert extract_content(html).text == "Colour: Black\nSize: M"


# --- chunk_text ----------------------------------------------------------------------


def numbered_words(count: int) -> str:
    return " ".join(f"word{index}" for index in range(count))


def assert_whole_words(chunk: str, text: str) -> None:
    start = text.index(chunk)
    end = start + len(chunk)
    assert start == 0 or text[start - 1].isspace()
    assert end == len(text) or text[end].isspace()
    assert chunk == chunk.strip()


def test_empty_text_gives_no_chunks():
    assert chunk_text("") == []
    assert chunk_text(" \n\t ") == []


def test_short_text_is_a_single_chunk():
    assert chunk_text("  A sturdy kettle.\n\nVolume: 1.7 l \n") == [
        "A sturdy kettle.\n\nVolume: 1.7 l"
    ]


def test_long_text_is_cut_into_chunks_of_about_the_target_size():
    text = numbered_words(1000)

    chunks = chunk_text(text)

    assert len(chunks) > 5
    assert all(len(chunk) <= CHUNK_SIZE for chunk in chunks)
    assert all(len(chunk) > CHUNK_SIZE - 20 for chunk in chunks[:-1])
    for chunk in chunks:
        assert_whole_words(chunk, text)


def test_chunks_overlap_and_cover_the_whole_text():
    text = numbered_words(1000)
    words = text.split()

    chunks = chunk_text(text)

    position = {word: index for index, word in enumerate(words)}
    spans = [(position[chunk.split()[0]], position[chunk.split()[-1]]) for chunk in chunks]
    assert spans[0][0] == 0
    assert spans[-1][1] == len(words) - 1
    for chunk, (first, last), (next_first, next_last) in zip(
        chunks, spans, spans[1:], strict=False
    ):
        assert first < next_first <= last < next_last
        repeated = " ".join(words[next_first : last + 1])
        assert chunk.endswith(repeated)
        assert CHUNK_OVERLAP - 20 < len(repeated) <= CHUNK_OVERLAP


def test_size_and_overlap_can_be_set():
    assert chunk_text("aa bb cc dd ee", size=8, overlap=2) == ["aa bb cc", "cc dd ee"]
    assert chunk_text("aa bb cc dd ee", size=8, overlap=0) == ["aa bb cc", "dd ee"]


def test_word_longer_than_a_chunk_is_kept_whole():
    long_word = "x" * 1000
    assert chunk_text(f"before {long_word} after", size=100, overlap=20) == [
        "before",
        long_word,
        "after",
    ]


def test_ukrainian_page_text_is_chunked_without_cutting_words():
    text = extract_content(load_fixture("content_uk.html")).text

    chunks = chunk_text(text)

    assert len(chunks) == 2
    for chunk in chunks:
        assert len(chunk) <= CHUNK_SIZE
        assert_whole_words(chunk, text)
    assert chunks[-1].endswith("Країна виробництва: Італія")
