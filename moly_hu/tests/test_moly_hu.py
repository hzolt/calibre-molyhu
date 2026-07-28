import datetime
from pathlib import Path

from lxml.html import fromstring

from moly_hu.moly_hu import (
    Book,
    book_page_urls_from_seach_page,
    generate_search_terms,
    parse_page,
)

test_inputs_path = Path(__file__).parent / "inputs"


def read_book(file_name: str) -> Book:
    book_page_content = Path(test_inputs_path / file_name).read_text(encoding="utf-8")
    return Book(fromstring(book_page_content))


def test_book_page_v2():
    book = read_book("book_page_raymond_feist_az_erzoszivu_magus.htm")

    assert book.authors() == ["Raymond E. Feist"]
    assert book.title() == "Az érzőszívű mágus"
    assert book.series() == ["A Résháború", 1]
    assert book.publisher() == "Unikornis"
    assert book.publication_date() == datetime.date(1991, 1, 1)
    assert book.isbn() == "9637519416"
    assert book.translator() == ["Kaposi Tamás"]
    assert book.cover_urls() == [
        "https://moly.hu/system/covers/big/covers_4959.jpg?1395344202"
    ]
    assert book.rating() == 5
    assert book.languages() == ["hu"]

    expected_tags = [
        "amerikai szerző",
        "elf",
        "fantasy",
        "felnőtté válás",
        "háború",
        "heroikus fantasy",
        "high fantasy",
        "ifjúsági",
        "kaland",
        "mágia",
        "magyar nyelvű",
        "portál fantasy",
        "regény",
        "sárkány",
        "sorozat része",
        "tündér",
        "varázsló",
    ]
    assert sorted(book.tags()) == sorted(expected_tags)  # type:ignore

    expected_description = "Pug, a varázsló inasa megmenti Carline hercegnőt a koboldoktól, ezért nemesi rangot kap… Barátját, Tomast, az utolsó aranysárkány gyönyörű aranykarddal és vérttel ajándékozza meg. A Királyságot több oldalról fenyegeti veszély: a harcias tsuranik és a Fekete Testvériség kegyetlen harcosai megpróbálják elfoglalni a földet, amelyet emberek, tündérek, törpék együtt védelmeznek. Pug egy Résen át másik térdimenzióba kerül, új személyiséget kap, de mágikus képességeivel felülkerekedik az elnyomó Nagy Emberek praktikáin…"
    assert book.description() == expected_description


def test_series_range_index_uses_first_number():
    # Omnibus editions list a volume range as the series index, e.g.
    # "(Aliens 6-7.)". Calibre needs a single integer, so the first number of
    # the range is used instead of crashing on int("6-7").
    html = (
        '<div id="content"><a class="action" href="/sorozatok/aliens">'
        "(Aliens 6-7.)</a></div>"
    )
    book = Book(fromstring(html))

    assert book.series() == ["Aliens", 6]


def test_publication_date_full_from_tooltip():
    # On current pages the year sits inside an <abbr> whose title holds the
    # full publication date, e.g. "Megjelenés időpontja: 2025. szeptember 4.".
    html = (
        '<div id="content"><div class="items"><div>'
        '<div><a href="/kiadok/szukits">Szukits</a>, Szeged, '
        "<abbr title='Megjelenés időpontja: 2025. szeptember  4.' "
        "class='tooltip'>2025</abbr></div>"
        "<div>404 oldal · <strong>ISBN</strong>: 9789634978084</div>"
        "</div></div></div>"
    )
    book = Book(fromstring(html))

    assert book.publication_date() == datetime.date(2025, 9, 4)


def test_publication_date_is_not_taken_from_isbn():
    # When an edition has no publication year, the year must not be matched
    # from the leading digits of the ISBN (e.g. "9789634978084" -> 9789).
    html = (
        '<div id="content"><div class="items"><div>'
        '<div><a href="/kiadok/szukits">Szukits</a>, Szeged </div>'
        "<div>500 oldal · <strong>ISBN</strong>: 9789634978084</div>"
        "</div></div></div>"
    )
    book = Book(fromstring(html))

    assert book.isbn() == "9789634978084"
    assert book.publication_date() is None


def test_publication_date_falls_back_to_bare_year():
    html = (
        '<div id="content"><div class="items"><div>'
        '<div><a href="/kiadok/szukits">Szukits</a>, Szeged, 2025 </div>'
        "<div>500 oldal · <strong>ISBN</strong>: 9789634978084</div>"
        "</div></div></div>"
    )
    book = Book(fromstring(html))

    assert book.publication_date() == datetime.date(2025, 1, 1)


def test_parse_page_accepts_str_and_bytes_with_a_charset_declaration():
    # moly.hu pages declare their own encoding. Handing that to lxml as a str
    # uses libxml2's unicode path, where older builds can abort with a fatal
    # "internal error" that recover mode does not absorb, so parse_page feeds
    # bytes instead. Both input shapes must yield the same tree.
    html = (
        '<!DOCTYPE html><html lang="hu"><head><meta charset="utf-8" />'
        "<title>t</title></head>"
        '<body><div id="content"><div class="authors">'
        '<a href="/alkotok/aisling-rawle">Aisling Rawle</a></div>'
        '<span class="item">A komplexum</span></div></body></html>'
    )

    from_str = Book(parse_page(html))
    from_bytes = Book(parse_page(html.encode("utf-8")))

    assert from_str.title() == "A komplexum"
    assert from_str.authors() == ["Aisling Rawle"]
    assert from_bytes.title() == from_str.title()
    assert from_bytes.authors() == from_str.authors()


def test_edition_fields_come_from_a_single_edition():
    # A book page lists every edition, each with its own publisher, year, ISBN
    # and translator. All the edition-derived getters must describe the same
    # (first) edition, otherwise a book with an old and a re-translated
    # edition would end up with a year from one and a translator from another.
    # This page also embeds a copy of an edition inside a review, and reuses
    # the "items" class for the review and citation blocks.
    book = read_book("book_page_dennis_e_taylor_mi_bob.htm")

    assert book.publisher() == "Metropolis Media"
    assert book.publication_date() == datetime.date(2017, 6, 12)
    assert book.isbn() == "9786155628221"
    assert book.translator() == ["Oszlánszky Zsolt"]


def test_translator_multiple():
    html = (
        '<div id="content"><div class="items"><div class="edition edition_1">'
        '<div><a href="/kiadok/szukits">Szukits</a>, Szeged, 2025 </div>'
        "<div>404 oldal<span> · </span><strong>ISBN</strong>: 9789634978084"
        "<span> · </span><strong>Fordította</strong>: "
        '<a href="/alkotok/kaposi-tamas">Kaposi Tamás</a>, '
        '<a href="/alkotok/nagy-imre">Nagy Imre</a></div>'
        "</div></div></div>"
    )
    book = Book(fromstring(html))

    assert book.translator() == ["Kaposi Tamás", "Nagy Imre"]


def test_translator_ignores_other_credits():
    # The edition line can credit more than the translator, and every credit
    # links into the same /alkotok/ namespace. Only the names behind the
    # "Fordította" label belong to the translator.
    html = (
        '<div id="content"><div class="items"><div class="edition edition_1">'
        '<div><a href="/kiadok/szukits">Szukits</a>, Szeged, 2025 </div>'
        "<div>404 oldal<span> · </span>"
        "<strong>Fordította</strong>: "
        '<a href="/alkotok/kaposi-tamas">Kaposi Tamás</a><span> · </span>'
        "<strong>Illusztrálta</strong>: "
        '<a href="/alkotok/rajzolo-bela">Rajzoló Béla</a></div>'
        "</div></div></div>"
    )
    book = Book(fromstring(html))

    assert book.translator() == ["Kaposi Tamás"]


def test_translator_is_none_without_label():
    html = (
        '<div id="content"><div class="items"><div class="edition edition_1">'
        '<div><a href="/kiadok/szukits">Szukits</a>, Szeged, 2025 </div>'
        "<div>404 oldal<span> · </span><strong>ISBN</strong>: 9789634978084"
        "</div></div></div></div>"
    )
    book = Book(fromstring(html))

    assert book.isbn() == "9789634978084"
    assert book.translator() is None


def test_book_with_empty_input():
    book = Book(fromstring("dummy data"))

    assert book.authors() == None
    assert book.title() == None
    assert book.series() == None
    assert book.publisher() == None
    assert book.publication_date() == None
    assert book.isbn() == None
    assert book.translator() == None
    assert book.cover_urls() == None
    assert book.tags() == None
    assert book.rating() == None
    assert book.languages() == None
    assert book.description() == None


def test_search_page():
    expected_urls = {
        "raymond-e-feist-janny-wurts-a-birodalom-leanya",
        "raymond-e-feist-a-demonkiraly-duhe-i-ii",
        "raymond-e-feist-janny-wurts-a-birodalom-szolgaloja-i-ii",
        "raymond-e-feist-sethanon-alkonya",
        "raymond-e-feist-a-kiraly-kaloza-i-ii",
        "raymond-e-feist-magus-a-mester",
        "raymond-e-feist-magus-a-tanitvany",
        "raymond-e-feist-ezusttovis",
        "raymond-e-feist-verbeli-herceg",
        "raymond-e-feist-az-erzoszivu-magus",
    }

    page_content = fromstring(
        Path(test_inputs_path / "search_page_raymond_feist.htm").read_text(
            encoding="utf-8"
        )
    )
    book_urls = book_page_urls_from_seach_page(page_content)

    assert book_urls == expected_urls


def test_search_page_no_results_ignores_widget_books():
    # When moly.hu has no match (e.g. a foreign ISBN), the result list is empty
    # but the page still renders sidebar widgets whose links reuse the
    # "book_selector" class. Those widget books must not leak out as results.
    page_content = fromstring(
        Path(test_inputs_path / "search_page_no_results.htm").read_text(
            encoding="utf-8"
        )
    )
    book_urls = book_page_urls_from_seach_page(page_content)

    assert book_urls == set()


def test_search_author_and_title():
    authors = ["Raymond E. Feist", "Dummy Additional Author"]
    title = "Az ​érzőszívű mágus"
    authors = [authors[0]]
    title = title
    identifiers = {}
    expected = [
        "Raymond E. Feist Az ​érzőszívű mágus",
        "Az ​érzőszívű mágus",
    ]
    result = generate_search_terms(title, authors, identifiers)
    assert result == expected


def test_search_isbn_only():
    identifiers = {
        "isbn": "9637519416",
        "moly_hu": "raymond-e-feist-az-erzoszivu-magus",
    }
    authors = []
    title = ""
    identifiers = {"isbn": identifiers["isbn"]}
    expected = [
        "9637519416",
    ]
    result = generate_search_terms(title, authors, identifiers)
    assert result == expected


def test_search_title_only():
    authors = []
    title = "Az ​érzőszívű mágus"
    identifiers = {}
    expected = [
        "Az ​érzőszívű mágus",
    ]
    result = generate_search_terms(title, authors, identifiers)
    assert result == expected


def test_search_order_if_everything_available():
    authors = ["Raymond E. Feist", "Dummy Additional Author"]
    title = "Az ​érzőszívű mágus"
    identifiers = {
        "isbn": "9637519416",
        "moly_hu": "raymond-e-feist-az-erzoszivu-magus",
    }
    authors = [authors[0]]
    title = title
    identifiers = identifiers
    expected = [
        "9637519416",
        "Raymond E. Feist Az ​érzőszívű mágus",
        "Az ​érzőszívű mágus",
    ]
    result = generate_search_terms(title, authors, identifiers)
    assert result == expected


def test_search_multiple_author():
    authors = ["Raymond E. Feist", "Dummy Additional Author"]
    title = "Az ​érzőszívű mágus"
    identifiers = {}
    expected = [
        "Raymond E. Feist Az ​érzőszívű mágus",
        "Dummy Additional Author Az ​érzőszívű mágus",
        "Az ​érzőszívű mágus",
    ]
    result = generate_search_terms(title, authors, identifiers)
    assert result == expected
