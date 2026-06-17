import datetime
from pathlib import Path

from lxml.html import fromstring

from moly_hu.moly_hu import Book, book_page_urls_from_seach_page, generate_search_terms

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


def test_book_with_empty_input():
    book = Book(fromstring("dummy data"))

    assert book.authors() == None
    assert book.title() == None
    assert book.series() == None
    assert book.publisher() == None
    assert book.publication_date() == None
    assert book.isbn() == None
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
