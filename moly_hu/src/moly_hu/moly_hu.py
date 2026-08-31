import datetime
import json
import re
from urllib.parse import quote_plus

from lxml.etree import strip_tags
from lxml.html import HTMLParser, fromstring

DOMAIN = "https://moly.hu"
BOOK_URL = DOMAIN + "/konyvek"
# The book page's statistics sub-page, holding the breakdown behind the single
# average the book page shows.
STATISTICS_PATH = "statisztika"

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


def parse_decimal(text):
    """The first number in a string, or None. Hungarian decimals use a comma."""
    if text is None:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", str(text))
    if match:
        return float(match.group().replace(",", "."))
    return None


def parse_count(text):
    """The first whole number in a string, or None.

    moly.hu groups thousands with a space, ordinary or non-breaking, which has
    to go before the digits read as one number.
    """
    if text is None:
        return None
    match = re.search(r"\d[\d\s]*", str(text))
    if match:
        return int(re.sub(r"\s", "", match.group()))
    return None


# How moly.hu marks an edition as an ebook. The reader icon on the edition line
# carries the label in its "data-title" and "title" attributes, the icon file
# itself is named after the reader, and the edition is tagged "ekönyv":
#
#   <img class="tooltip" src=".../e-book-reader-black-....png"
#        data-title="Ekönyv" title="Ekönyv"/>
#   ... <a class="tag" href="/cimkek/ekonyv">ekönyv</a>
#
# All three are matched because moly.hu does not render them consistently:
# older pages carry the title attribute without the data-title spelling, and
# the tag link is missing from the edition blocks embedded elsewhere.
EBOOK_LABELS = ("ekönyv", "e-könyv", "ebook", "e-book")
EBOOK_TAG_PATH = "/cimkek/ekonyv"
EBOOK_ICON_NAME = "e-book-reader"


def is_ebook_edition(edition):
    """Whether an edition node describes an ebook rather than a printed book."""
    if edition is None:
        return False
    for label in edition.xpath(".//*/@data-title | .//*/@title"):
        if str(label).strip().lower() in EBOOK_LABELS:
            return True
    for href in edition.xpath(".//a/@href"):
        if str(href).split("?")[0].rstrip("/").endswith(EBOOK_TAG_PATH):
            return True
    for src in edition.xpath(".//img/@src"):
        if EBOOK_ICON_NAME in str(src):
            return True
    return False


# Where a title can be cut short. moly.hu files a book under the part before
# the separator and renders the rest as a subtitle of its own, so the library's
# "A pénz istenei: A Wall Street összeesküvése Amerika leigázására" is simply
# "A pénz istenei" there and the whole string finds nothing.
#
# The surrounding space is part of the pattern on purpose: a colon has to be
# followed by one, which keeps a time like "20:00" together, and a dash needs
# one on both sides, which keeps "Aliens-gyűjtemény" and "e-mail" whole. The en
# and em dash are matched as well, both common in Hungarian titles.
SUBTITLE_SEPARATOR = re.compile(r":\s|\s[-–—]\s")


def title_variants(title):
    """The title and the shorter forms of it worth searching for.

    The full title comes first, then the part before each separator, longest
    first, so that the most specific search is always tried before a broader
    one. A title without a separator yields itself alone.
    """
    if not title or not title.strip():
        return []
    variants = [title.strip()]
    # Reversed: the last separator gives the longest prefix.
    for match in reversed(list(SUBTITLE_SEPARATOR.finditer(title))):
        prefix = title[: match.start()].strip()
        if prefix:
            variants.append(prefix)
    return list(dict.fromkeys(variants))


def generate_search_terms(title, authors, identifiers, normalise_title=None):
    """The moly.hu searches to run for a book, in the order to run them.

    An ISBN first, being an exact match, then author and title together
    followed by the title on its own - for each form of the title in turn, so
    that a search for the whole title always precedes one for a part of it.

    ``normalise_title`` is applied to each title form when given: calibre's
    metadata source hands over its own tokenizer, which drops leading articles
    and punctuation. It runs after the title is split rather than before,
    because it strips the very colon the split needs.
    """
    search_terms = list()
    isbn = identifiers.get("isbn")
    if isbn:
        search_terms.append(isbn)
    for variant in title_variants(title):
        if normalise_title is not None:
            variant = (normalise_title(variant) or "").strip()
            if not variant:
                continue
        if authors:
            for author in authors:
                search_terms.append(f"{author} {variant}")
        search_terms.append(variant)
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


def statistics_url_for_id(id):
    return f"{book_url_for_id(id)}/{STATISTICS_PATH}"


# FIXME(crash): add isvalid() method to check the required values (id, isbn, title etc.)
class Book:
    def __init__(self, xml_root, moly_id=None):
        self._xml_root = xml_root
        self._moly_id = moly_id

    def __str__(self) -> str:
        author = (self.authors()[0:1] if self.authors() else ("Unknown",))[0]
        series = f" [{self.series()[0]} / {self.series()[1]}]" if self.series() else ""
        # The edition the data was read from is named, so that a run from the
        # command line shows which of a book's editions answered.
        edition = "ekönyv" if self.is_ebook() else "nyomtatott"
        return f"{author}: {self.title()}{series} ({self.publisher()}, {self.publication_date()}, {self.isbn()}, {edition}, {self.moly_id()})"

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

    def _edition_nodes(self):
        """Every edition node of the book, in the order the page lists them."""
        return self._xml_root.xpath(
            '//*[@id="content"]//*[@class="items"]'
            '/div[contains(concat(" ", normalize-space(@class), " "), " edition ")]'
        ) or self._xml_root.xpath(
            # Older layouts render the edition without the "edition" class.
            # The parentheses matter: "(...)[1]" is the first node in the
            # document, "...[1]" would be the first one under every parent.
            # Note that "items" is also the class of the review and citation
            # blocks, hence taking only the first one.
            '(//*[@id="content"]//*[@class="items"])[1]/div'
        )

    def _edition_node(self):
        # A book page lists one node per edition, each with its own publisher,
        # year, ISBN and translator. Every edition-derived getter reads from
        # this single node so the values always describe the same edition; a
        # book with an old and a re-translated edition would otherwise mix
        # them.
        #
        # The ebook edition is preferred where the page has one, because that
        # is the edition a calibre library actually holds: its ISBN, page
        # count and publication date are its own, and filing the printed
        # edition's ISBN against an epub is simply wrong. Where no edition is
        # marked as an ebook the first one is used, as before.
        editions = self._edition_nodes()
        if not editions:
            return None
        # Only the editions of the block the first one sits in are considered,
        # so that an edition rendered inside a review further down the page
        # cannot win the preference.
        block = editions[0].getparent()
        for edition in editions:
            if edition.getparent() is block and is_ebook_edition(edition):
                return edition
        return editions[0]

    def is_ebook(self):
        """Whether the edition the data is read from is an ebook."""
        return is_ebook_edition(self._edition_node())

    def publisher(self):
        edition = self._edition_node()
        if edition is None:
            return None
        # The publisher is the /kiadok/ link of the edition line, and being
        # named by its href it is found wherever the layout puts it - the
        # positional lookups below miss it as soon as anything is nested
        # differently, which is what happens on a page whose editions are
        # wrapped in the "Megnyitás" anchor.
        for name in edition.xpath('.//a[starts-with(@href, "/kiadok/")]/text()'):
            if name.strip():
                return name.strip()
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
        """The ISBN of the edition the rest of the data comes from.

        Read from the edition node rather than by position on the page, so
        that it belongs to the same edition as the publisher, the date and the
        translator - on a book with both a printed and an ebook edition the
        positional lookup always answered with the printed one.
        """
        return self._isbn(self._edition_node())

    def isbns(self):
        """The ISBN of every edition listed, in page order, or None.

        A library holding the paperback and a page whose data is read off the
        ebook edition still describe the same book, so a caller confirming a
        match by ISBN has to be able to see all of them.
        """
        found = []
        for edition in self._edition_nodes():
            isbn = self._isbn(edition)
            if isbn and isbn not in found:
                found.append(isbn)
        return found or None

    def _isbn(self, edition):
        if edition is None:
            return None
        # The number is the text right behind the "ISBN" label:
        #   <strong>ISBN</strong>: 9789635511235
        # Taking it from there keeps a page count or a cover id from being
        # read as an ISBN.
        for label in edition.xpath('.//strong[starts-with(normalize-space(), "ISBN")]'):
            match = re.search(r"(\d{13}|\d{10})", label.tail or "")
            if match:
                return match.group(1)
        for text in edition.xpath(".//text()"):
            match = re.search(r"(?<!\d)(\d{13}|\d{10})(?!\d)", text)
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

    def _aggregate_rating(self):
        """The schema.org rating block moly.hu embeds in the page head.

        The head states the score and the number of ratings outright:

            <script type="application/ld+json">
            {"@type": "Book", "name": "...",
             "aggregateRating": {"@type": "AggregateRating",
                                 "ratingValue": "90%", "ratingCount": "5"}}
            </script>

        Preferred over the header markup because it does not depend on how the
        page is laid out. The header renders the percentage differently for a
        book with few ratings, and reading it there comes back empty on
        exactly those pages, while this block still states the number.
        """
        for block in self._xml_root.xpath(
            '//script[@type="application/ld+json"]/text()'
        ):
            try:
                data = json.loads(block)
            except ValueError:
                continue
            # A page may carry several blocks, and a block may carry several
            # records, only one of which is the book.
            for record in data if isinstance(data, list) else [data]:
                if not isinstance(record, dict):
                    continue
                rating = record.get("aggregateRating")
                if isinstance(rating, dict):
                    return rating
        return None

    def _rating_percent_text(self):
        # The header of a book page carries the score as a percentage:
        #   <span class="stat"><span class="rating">
        #     <span class="like_count" title="...">94%</span>
        #   </span>...
        # "like_count" is also the class of the score on every review block
        # further down the page, dozens of them, and those are under #content
        # too. The "rating" ancestor is what keeps them out, so it has to stay
        # in the path. Both classes are matched a token at a time, because
        # either can be rendered alongside a second one.
        nodes = self._xml_root.xpath(
            '//*[@id="content"]'
            '//*[contains(concat(" ", normalize-space(@class), " "), " rating ")]'
            '//*[contains(concat(" ", normalize-space(@class), " "), " like_count ")]'
            "/text()"
        )
        return nodes[0] if nodes else None

    def rating(self):
        percent = self.rating_percent()
        if percent is None:
            return None
        return round(percent * 0.05)

    def rating_percent(self):
        """The score as moly.hu shows it: a percentage from 0 to 100.

        ``rating()`` rounds this onto calibre's 0-5 scale, which loses most of
        it - 90% and 94% are both 5 stars. This keeps the number as it stands
        on the page, for a column that can hold it.
        """
        # A page that states nobody has rated the book has no score to give,
        # whatever else it renders: a "0%" there is the absence of ratings, not
        # a book everyone disliked. The stated count is what this turns on
        # rather than rating_count(), which reads that same zero as absent, so
        # that a book whose page shows a percentage but no count link - the
        # count is genuinely unknown there - still reports its score.
        if self._stated_rating_count() == 0:
            return None
        stated = (self._aggregate_rating() or {}).get("ratingValue")
        # Only taken when it is written as a percentage. schema.org means
        # ratingValue to be a score out of bestRating, so a day when moly.hu
        # makes the field conform would otherwise turn a 4.5 into 4.5%. The
        # header still shows the percentage and is read instead.
        if stated is not None and "%" in str(stated):
            percent = parse_decimal(stated)
            if percent is not None:
                return percent
        return parse_decimal(self._rating_percent_text())

    def _statistic_link(self):
        """The "62 csillagozás" anchor, which both names the rating count and
        points at the book's statistics page.

        The class is "statistic_link modal", hence the concat() match rather
        than an equality test. A book nobody has rated yet does not render the
        anchor at all.
        """
        nodes = self._xml_root.xpath(
            '//*[@id="content"]//a'
            '[contains(concat(" ", normalize-space(@class), " "), " statistic_link ")]'
        )
        return nodes[0] if nodes else None

    def _stated_rating_count(self):
        """The rating count exactly as the page puts it, a zero included."""
        stated = (self._aggregate_rating() or {}).get("ratingCount")
        if stated is not None:
            count = parse_count(stated)
            if count is not None:
                return count
        link = self._statistic_link()
        return parse_count(link.text) if link is not None and link.text else None

    def rating_count(self):
        """How many people rated the book: the "62 csillagozás" figure.

        A book nobody has rated yet is reported as a zero rather than left out
        - the schema.org block carries "ratingCount": "0" - and a zero is not a
        count anyone wants recorded. It reads as absent, so that writing it to
        a library leaves the column as it was instead of filing a 0 there.
        """
        return self._stated_rating_count() or None

    def statistics_url(self):
        """Where moly.hu breaks the ratings down, e.g.
        https://moly.hu/konyvek/dennis-e-taylor-mi-bob/statisztika

        The page's own link is preferred so that a change of path on moly.hu
        follows automatically. Where the link is missing the URL is built from
        the id, but only for a book that has been rated: the statistics page
        exists only once there is something to break down, so a book with
        neither a rating nor a rating count has no URL to give.
        """
        # An unrated book can still carry the link, and it points at a page
        # with nothing on it. Where the page states the count as zero that is
        # not a URL worth reporting, however it was arrived at.
        if self._stated_rating_count() == 0:
            return None
        link = self._statistic_link()
        href = link.get("href") if link is not None else None
        if href:
            return href if href.startswith("http") else DOMAIN + href
        if self._moly_id and (
            self.rating_count() is not None or self.rating_percent() is not None
        ):
            return statistics_url_for_id(self._moly_id)
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
