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
    assert book.rating_percent() == 94.0
    assert book.rating_count() == 62
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


def test_parse_page_decodes_utf8_without_a_charset_declaration():
    # moly.hu is UTF-8 but announces it with the HTML5 <meta charset="utf-8">,
    # which older libxml2 builds ignore. Left to guess, libxml2 falls back to
    # Latin-1 and mangles every accented character ("Század" -> "SzÃ¡zad").
    # The page is deliberately built without any charset declaration here, so
    # this fails unless parse_page states the encoding itself.
    html = (
        '<!DOCTYPE html><html lang="hu"><head><title>t</title></head>'
        '<body><div id="content"><div class="authors">'
        '<a href="/alkotok/aisling-rawle">Aisling Rawle</a></div>'
        '<span class="item">A ​komplexum</span>'
        '<div class="items"><div class="edition edition_1">'
        '<div><a href="/kiadok/xxi-szazad">XXI. Század</a>, Budapest, 2026 </div>'
        "<div>352 oldal<span> · </span><strong>Fordította</strong>: "
        '<a href="/alkotok/pelda-eva">Példa Éva</a></div>'
        "</div></div></div></body></html>"
    )

    from_str = Book(parse_page(html))
    from_bytes = Book(parse_page(html.encode("utf-8")))

    for book in (from_str, from_bytes):
        # title() also strips the zero width space moly.hu puts in titles,
        # which only works when the bytes were decoded as UTF-8 to begin with.
        assert book.title() == "A komplexum"
        assert book.authors() == ["Aisling Rawle"]
        assert book.publisher() == "XXI. Század"
        assert book.translator() == ["Példa Éva"]


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


def test_rating_is_read_from_the_book_and_not_from_a_review():
    # Every review on the page carries its own "like_count", and this page
    # renders its title in a bare <h1> rather than the <h1 class="book"> of
    # newer layouts, so neither the class alone nor the heading can be the
    # anchor for the book's own score.
    book = read_book("book_page_dennis_e_taylor_mi_bob.htm")

    assert book.rating_percent() == 84.0
    assert book.rating_count() == 95
    assert book.rating() == 4


def test_statistics_url_comes_from_the_page():
    # The "95 csillagozás" link the book page already carries, so no id is
    # needed to find the statistics page.
    book = read_book("book_page_dennis_e_taylor_mi_bob.htm")

    assert (
        book.statistics_url()
        == "https://moly.hu/konyvek/dennis-e-taylor-mi-bob/statisztika"
    )


def test_statistics_url_falls_back_to_the_id():
    # A book nobody has rated yet renders no "csillagozás" link at all, but
    # its statistics page exists and its address follows from the id.
    html = '<div id="content"><h1>Egy könyv</h1></div>'
    book = Book(fromstring(html), moly_id="egy-szerzo-egy-konyv")

    assert (
        book.statistics_url()
        == "https://moly.hu/konyvek/egy-szerzo-egy-konyv/statisztika"
    )


def test_rating_is_read_from_the_embedded_json():
    # A book with few ratings does not render the percentage in the header the
    # way a well read one does, so the header scrape finds nothing. The
    # schema.org block in the head states it either way. Taken from the page
    # of "Földvári-Oláh Csaba: Szeánsz", which reported a rating count but no
    # rating until this was read.
    html = (
        '<html><head><script type="application/ld+json">\n'
        '{"@context": "https://schema.org/", "@type": "Book",\n'
        ' "name": "Földvári-Oláh Csaba: Szeánsz",\n'
        ' "aggregateRating": {"@type": "AggregateRating",\n'
        '                     "ratingValue": "90%", "ratingCount": "5"}}\n'
        "</script></head><body>"
        '<div id="content"><span class="stat">'
        '<a class="statistic_link modal" href="/konyvek/x/statisztika">'
        "5 csillagozás</a></span></div></body></html>"
    )
    book = Book(fromstring(html))

    assert book.rating_percent() == 90.0
    assert book.rating_count() == 5
    # 90% * 0.05 is 4.5, and round() breaks a tie towards the even number.
    assert book.rating() == 4


def test_rating_falls_back_to_the_header_when_the_json_is_not_a_percentage():
    # schema.org means ratingValue to be a score out of bestRating, so a value
    # without a "%" is not the percentage this reads and must not be taken for
    # one - 4.5 is not 4.5%.
    html = (
        '<html><head><script type="application/ld+json">\n'
        '{"@type": "Book", "aggregateRating": {"ratingValue": "4.5",\n'
        '                                      "ratingCount": "62"}}\n'
        "</script></head><body>"
        '<div id="content"><span class="stat">'
        '<span class="rating"><span class="like_count">94%</span></span>'
        "</span></div></body></html>"
    )
    book = Book(fromstring(html))

    assert book.rating_percent() == 94.0
    assert book.rating_count() == 62


def test_rating_is_read_when_the_classes_carry_a_second_token():
    html = (
        '<div id="content"><span class="stat">'
        '<span class="rating fade"><span class="like_count small">73%</span></span>'
        "</span></div>"
    )
    book = Book(fromstring(html))

    assert book.rating_percent() == 73.0


def test_rating_count_strips_grouped_thousands():
    # moly.hu groups thousands with a space, ordinary or non-breaking.
    html = (
        '<div id="content"><span class="stat">'
        '<span class="rating"><span class="like_count">92%</span></span>'
        '<a class="statistic_link modal" href="/konyvek/x/statisztika">'
        "1 234 csillagozás</a></span></div>"
    )
    book = Book(fromstring(html))

    assert book.rating_percent() == 92.0
    assert book.rating_count() == 1234


def test_rating_is_none_without_the_stat_block():
    html = '<div id="content"><h1>Egy könyv</h1></div>'
    book = Book(fromstring(html))

    assert book.rating_percent() is None
    assert book.rating_count() is None
    assert book.rating() is None


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
    assert book.rating_percent() == None
    assert book.rating_count() == None
    assert book.statistics_url() == None
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
