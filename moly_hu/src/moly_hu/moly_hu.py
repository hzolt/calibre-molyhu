import datetime
import re
from urllib.parse import quote_plus

from lxml.etree import strip_tags
from lxml.html import HTMLParser, fromstring

DOMAIN = "https://moly.hu"
BOOK_URL = DOMAIN + "/konyvek"

HUNGARIAN_MONTHS = {
    "január": 1,
    "február": 2,
    "március": 3,
    "április": 4,
    "május": 5,
    "június": 6,
    "július": 7,
    "augusztus": 8,
    "szeptember": 9,
    "október": 10,
    "november": 11,
    "december": 12,
}


def parse_hungarian_date(text):
    """Parse a moly.hu publication date into a ``datetime.date``.

    Handles a full date ("2025. szeptember 4."), a year and month
    ("2025. szeptember") and a bare year ("2025"). Missing parts default to
    the first month/day. Returns ``None`` when no year can be found.
    """
    months = "|".join(HUNGARIAN_MONTHS)
    full = re.search(rf"(\d{{4}})\.\s*({months})\s+(\d{{1,2}})", text, re.IGNORECASE)
    if full:
        return datetime.date(
            int(full.group(1)),
            HUNGARIAN_MONTHS[full.group(2).lower()],
            int(full.group(3)),
        )
    year_month = re.search(rf"(\d{{4}})\.\s*({months})", text, re.IGNORECASE)
    if year_month:
        return datetime.date(
            int(year_month.group(1)), HUNGARIAN_MONTHS[year_month.group(2).lower()], 1
        )
    year = re.search(r"(?<!\d)(1\d{3}|20\d{2})(?!\d)", text)
    if year:
        return datetime.date(int(year.group(1)), 1, 1)
    return None


def generate_search_terms(title, authors, identifiers):
    search_terms = list()
    isbn = identifiers.get("isbn")
    if isbn:
        search_terms.append(isbn)
    if authors and title:
        for author in authors:
            search_terms.append(f"{author} {title}")
    if title:
        search_terms.append(title)
    return list(dict.fromkeys(search_terms))


def parse_page(content):
    """Parse a moly.hu page into an lxml tree.

    moly.hu serves UTF-8, and both halves of this matter:

    A str is encoded to UTF-8 bytes first. Handing lxml a str sends libxml2
    down its unicode parsing path, where some pages abort with a fatal
    "XMLSyntaxError: internal error". Being fatal, the recover mode
    lxml.html.fromstring enables by default does not absorb it, and the
    whole page is lost.

    The encoding is then stated explicitly rather than left to libxml2.
    moly.hu announces itself with the HTML5 <meta charset="utf-8">, which
    older libxml2 builds - such as the one calibre bundles - do not read;
    they only understand the <meta http-equiv="Content-Type"> spelling. With
    no encoding it recognises, libxml2 falls back to Latin-1 and every
    accented character arrives mangled ("Század" -> "SzÃ¡zad").
    """
    if isinstance(content, str):
        content = content.encode("utf-8", errors="replace")
    # A parser per call: lxml parser objects must not be shared between
    # threads, and calibre runs identify() on worker threads.
    return fromstring(content, parser=HTMLParser(encoding="utf-8"))


def book_for_id(book_id, fetch_page_content):
    url = f"{BOOK_URL}/{book_id}"
    book_page = fetch_page_content(url)
    if book_page:
        return Book(xml_root=parse_page(book_page), moly_id=book_id)
    return None


def book_page_urls_from_seach_page(xml_root):
    book_url_prefix = "/konyvek/"
    # Only the genuine search results live inside the "search_area" container.
    # The same "book_selector" class is reused by sidebar widgets (newest
    # releases, recommendations, ...) that every moly.hu page renders. Scoping
    # to "search_area" keeps those out, so a search with no real hits returns
    # nothing instead of unrelated widget books.
    book_list_root = xml_root.xpath(
        '//div[@class="search_area"]//a[@class="book_selector"]'
    )
    matches = set()
    for book_item in book_list_root:
        strip_tags(book_item, "strong")
        for url in book_item.xpath("@href"):
            if url.startswith(book_url_prefix):
                matches.add(url[len(book_url_prefix) :])
    return matches


def search(keyword, fetch_page_content):
    search_url = f"{DOMAIN}/kereses?utf8=%E2%9C%93&query=" + quote_plus(keyword)
    content = fetch_page_content(search_url)
    return book_page_urls_from_seach_page(parse_page(content))


def book_url_for_id(id):
    return f"{BOOK_URL}/{id}"


# FIXME(crash): add isvalid() method to check the required values (id, isbn, title etc.)
class Book:
    def __init__(self, xml_root, moly_id=None):
        self._xml_root = xml_root
        self._moly_id = moly_id

    def __str__(self) -> str:
        author = (self.authors()[0:1] if self.authors() else ("Unknown",))[0]
        series = f" [{self.series()[0]} / {self.series()[1]}]" if self.series() else ""
        return f"{author}: {self.title()}{series} ({self.publisher()}, {self.publication_date()}, {self.isbn()}, {self.moly_id()})"

    def moly_id(self):
        return self._moly_id

    def authors(self):
        author_nodes = self._xml_root.xpath(
            '//*[@id="content"]//div[@class="authors"]/a/text()'
        )
        if author_nodes:
            return [str(author) for author in author_nodes]
        return None

    def title(self):
        title_node = self._xml_root.xpath(
            '//*[@id="content"]//*[@class="fn"]/text()'
        ) or self._xml_root.xpath('//*[@id="content"]//*[@class="item"]/text()')
        if title_node:
            # Cimből a ZWJ (zero-width joiner = nulla szélességű szóköz) karakter (\u200b) eltávolítása
            return title_node[0].strip().replace("\u200b", "")
        return None

    def series(self):
        series_node = self._xml_root.xpath(
            '//*[@id="content"]//*[@class="action"]/text()'
        )
        if not series_node:
            return None

        series = series_node[0].strip("().").rsplit(" ", 1)
        if len(series) < 2:
            return None

        if series[1] == "kiadás":
            return None
        try:
            series[1] = int(series[1])
        except Exception:
            # The index can be a range like "1-2" or "6-7" (omnibus
            # editions). Calibre needs a single integer, so fall back to the
            # first number in the range, or 1 if there is no number at all.
            match = re.match(r"\d+", series[1])
            series[1] = int(match.group()) if match else 1

        return series

    def _edition_node(self):
        # A book page lists one node per edition, each with its own publisher,
        # year, ISBN and translator. Every edition-derived getter reads from
        # this single node so the values always describe the same edition; a
        # book with an old and a re-translated edition would otherwise mix
        # them. The first edition is used, which is what the positional
        # lookups below have always effectively picked.
        editions = self._xml_root.xpath(
            '//*[@id="content"]//*[@class="items"]'
            '/div[contains(concat(" ", normalize-space(@class), " "), " edition ")]'
        ) or self._xml_root.xpath(
            # Older layouts render the edition without the "edition" class.
            # The parentheses matter: "(...)[1]" is the first node in the
            # document, "...[1]" would be the first one under every parent.
            # Note that "items" is also the class of the review and citation
            # blocks, hence taking only the first one.
            '(//*[@id="content"]//*[@class="items"])[1]/div[1]'
        )
        return editions[0] if editions else None

    def publisher(self):
        edition = self._edition_node()
        if edition is None:
            return None
        old_publisher = self._publisher(edition, "./div[1]/a/text()")
        # "+" is the text of the bookmark_button div, which current layouts
        # render as the first child, pushing the publisher one div further.
        if old_publisher and old_publisher != "+":
            return old_publisher
        return self._publisher(edition, "./div[2]/a/text()")

    def _publisher(self, edition, xpath):
        publisher_node = edition.xpath(xpath)
        if publisher_node:
            return publisher_node[0]
        return None

    def publication_date(self):
        edition = self._edition_node()
        if edition is None:
            return None
        # The edition line exposes the full publication date in the tooltip of
        # the "Megjelenés időpontja:" abbreviation, e.g.
        # <abbr title="Megjelenés időpontja: 2025. szeptember 4.">2025</abbr>.
        titles = edition.xpath(".//abbr/@title")
        for title in titles:
            if "Megjelenés időpontja" in title:
                date = parse_hungarian_date(title)
                if date:
                    return date
        # Fallback for editions that only expose a bare year on the edition
        # line (older layouts where the year is plain text, not a tooltip).
        return self._publication_date(edition, ".//text()")

    def _publication_date(self, edition, xpath):
        publication_node = edition.xpath(xpath)
        for publication_value in publication_node:
            # Match a plausible publication year (1000-2099) that is not part
            # of a longer number. Without the digit guards a bare "\d{4}" would
            # match the leading digits of an ISBN (e.g. "9789634978084" -> 9789)
            # whenever the edition has no year, yielding a bogus pubdate.
            match = re.search(r"(?<!\d)(1\d{3}|20\d{2})(?!\d)", publication_value)
            if match:
                return datetime.date(int(match.group(1)), 1, 1)
        return None

    def isbn(self):
        return self._isbn(
            '//*[@id="content"]//*[@class="items"]/div/div[2]/text()'
        ) or self._isbn('//*[@id="content"]//*[@class="items"]/div/div[3]/text()')

    def _isbn(self, xpath):
        isbn_node = self._xml_root.xpath(xpath)
        for isbn_value in isbn_node:
            match = re.search(r"(\d{13}|\d{10})", isbn_value)
            if match:
                return match.group(1)
        return None

    def translator(self):
        edition = self._edition_node()
        if edition is None:
            return None
        # The translator sits on the same line as the ISBN, behind a
        # "Fordította" (or "Fordították") label:
        #   ... <strong>ISBN</strong>: 963... ·
        #       <strong>Fordította</strong>: <a href="/alkotok/...">Név</a>
        # The label is the only reliable anchor: the line has no class of its
        # own, and its position varies between layouts. Collecting every
        # /alkotok/ link of the line would also pick up other credits such as
        # "Illusztrálta", so the walk stops at the next label.
        labels = edition.xpath('.//strong[starts-with(normalize-space(), "Fordít")]')
        if not labels:
            return None

        translators = []
        for sibling in labels[0].itersiblings():
            if sibling.tag == "strong":
                break
            if sibling.tag == "a" and (sibling.get("href") or "").startswith(
                "/alkotok/"
            ):
                name = (sibling.text or "").strip()
                if name:
                    translators.append(name)
        return translators or None

    def cover_urls(self):
        book_covers = self._xml_root.xpath('(//*[@class="coverbox"]//a/@href)')
        if book_covers:
            return [f"{DOMAIN}{cover_url}" for cover_url in book_covers]
        return None

    def tags(self):
        tags_node = (
            self._xml_root.xpath('//*[@id="tags"]//*[@class="hover_link"]/text()')
            or self._xml_root.xpath(
                '//*[@id="book_tags"]//*[@class="hover_link"]/text()'
            )
            or self._xml_root.xpath('//*[@id="book_tags"]//*[@rel="tag"]/text()')
        )
        tags = [str(text) for text in tags_node if text.strip()]
        if tags:
            return tags
        return None

    def rating(self):
        rating_node = self._xml_root.xpath(
            '//*[@id="content"]//*[@class="rating"]//*[@class="like_count"]/text()'
        )
        if rating_node:
            return round(float(rating_node[0].strip("%").strip()) * 0.05)
        return None

    def languages(self):
        tags = self.tags()
        if not tags:
            return None
        langs = []
        for tag in tags:
            langId = self._translateLanguageToCode(tag)
            if langId is not None:
                langs.append(langId)
        if not langs:
            return ["hu"]
        return langs

    def _translateLanguageToCode(self, displayLang):
        displayLang = displayLang.lower().strip() if displayLang else None
        langTbl = {
            None: "und",
            "angol nyelvű": "en",
            "német nyelvű": "de",
            "francia nyelvű": "fr",
            "olasz nyelvű": "it",
            "spanyol nyelvű": "es",
            "orosz nyelvű": "ru",
            "török nyelvű": "tr",
            "görüg nyelvű": "gr",
            "kínai nyelvű": "cn",
            "japán nyelvű": "jp",
            "magyar nyelvű": "hu",
        }
        return langTbl.get(displayLang, None)

    def description(self):
        description_node = self._xml_root.xpath(
            '//*[@id="content"]//*[@class="text" and @id="full_description"]/p/text()'
        ) \
        or self._xml_root.xpath('//*[@id="content"]//*[@class="text"]/p/text()') \
        or self._xml_root.xpath('//*[@id="content"]//*[@class="text shrinkable"]/p/text()')
        if description_node:
            join_desc_node = "\n".join(description_node)
            join_desc_node = join_desc_node.replace("\n\n", "\n")
            join_desc_node = join_desc_node.replace("\n \n", "\n")
            join_desc_node = join_desc_node.replace(
                "Vigyázat! Cselekményleírást tartalmaz.\n", ""
            )
            return join_desc_node
        return None
