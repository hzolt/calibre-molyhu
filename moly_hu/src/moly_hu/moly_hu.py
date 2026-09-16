import datetime
import json
import re
import unicodedata
from functools import cached_property
from urllib.parse import quote_plus

from lxml.html import HTMLParser, fromstring

DOMAIN = "https://moly.hu"
BOOK_URL = DOMAIN + "/konyvek"
# The identifier type calibre and calibre-web file a moly.hu id under, defined
# once here so that every front end names it the same way.
MOLY_ID_KEY = "moly_hu"
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


# How much of a date a page actually stated. The missing parts are filled in
# with the first month and day, so the date alone cannot tell "2017" from
# "2017. január 1.", and one edition's date can only be sharpened with
# another's when it is known which parts are real.
DAY_PRECISION = 3
MONTH_PRECISION = 2
YEAR_PRECISION = 1

# A plausible publication year, 1000-2099, that is not part of a longer number.
# Without the digit guards a bare "\d{4}" would match the leading digits of an
# ISBN ("9789634978084" -> 9789) whenever a line states no year.
YEAR_PATTERN = re.compile(r"(?<!\d)(1\d{3}|20\d{2})(?!\d)")
PAGE_COUNT_UNIT = "oldal"


def bare_year(text):
    """The first plausible publication year in a text, or None.

    A number followed by "oldal" is a page count, not a year, however many
    digits it has: an omnibus of 1024 pages was published in no such year.
    """
    text = text or ""
    for match in YEAR_PATTERN.finditer(text):
        if text[match.end() :].lstrip().startswith(PAGE_COUNT_UNIT):
            continue
        return int(match.group(1))
    return None


def parse_hungarian_date_precision(text):
    """A moly.hu publication date as ``(date, precision)``.

    Handles a full date ("2025. szeptember 4."), a year and month
    ("2025. szeptember") and a bare year ("2025"). Missing parts default to
    the first month/day, and the precision says which of them were stated.
    Returns ``(None, None)`` when no year can be found.
    """
    months = "|".join(HUNGARIAN_MONTHS)
    full = re.search(rf"(\d{{4}})\.\s*({months})\s+(\d{{1,2}})", text, re.IGNORECASE)
    if full:
        return (
            datetime.date(
                int(full.group(1)),
                HUNGARIAN_MONTHS[full.group(2).lower()],
                int(full.group(3)),
            ),
            DAY_PRECISION,
        )
    year_month = re.search(rf"(\d{{4}})\.\s*({months})", text, re.IGNORECASE)
    if year_month:
        return (
            datetime.date(
                int(year_month.group(1)),
                HUNGARIAN_MONTHS[year_month.group(2).lower()],
                1,
            ),
            MONTH_PRECISION,
        )
    year = bare_year(text)
    if year:
        return datetime.date(year, 1, 1), YEAR_PRECISION
    return None, None


def parse_hungarian_date(text):
    """Parse a moly.hu publication date into a ``datetime.date``."""
    return parse_hungarian_date_precision(text)[0]


def sharpens(candidate, candidate_precision, date, precision):
    """Whether a candidate date is a more precise reading of the same date.

    A printed edition's "2017. június 12." sharpens an ebook edition's bare
    "2017", because the year they both state agrees. It has to agree on every
    part the coarser date states, so a 2015 hardback cannot lend its day to a
    2017 ebook, and a March date cannot sharpen "2023. február".
    """
    if candidate is None or date is None:
        return False
    if candidate_precision <= precision:
        return False
    if candidate.year != date.year:
        return False
    if precision >= MONTH_PRECISION and candidate.month != date.month:
        return False
    return True


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


# An ISBN as moly.hu prints it: the thirteen digits of a current number, or the
# ten of an older one, whose check digit can be an X.
ISBN_PATTERN = re.compile(r"(?<![\dXx])(\d{13}|\d{9}[\dXx])(?![\dXx])")


def normalise_isbn(text):
    """An ISBN reduced to its digits and check letter, in upper case, or None.

    Hyphens, spaces and a lower-case x are all spellings of the same number,
    and two of them only compare equal once they are spelt the same way.
    """
    if not text:
        return None
    return re.sub(r"[^0-9Xx]", "", str(text)).upper() or None


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


def title_fragments(title):
    """Every form of the title a page may legitimately be recognised by.

    ``title_variants`` keeps the leading parts alone, which is what a search
    wants: dropping the subtitle broadens a search, dropping the main title
    does not. Recognising a page needs both halves, because moly.hu files a
    translated book under both of its titles and puts the original one first -
    the page's "Spiral – Kicsúszás" is the library's plain "Kicsúszás".

    The whole title stays first, as ``title_variants`` has it, so that a caller
    can still tell a full title from a part of one by position.
    """
    variants = title_variants(title)
    if not variants:
        return []
    parts = [part.strip() for part in SUBTITLE_SEPARATOR.split(title)]
    return list(dict.fromkeys(variants + [part for part in parts if part]))


def strip_invisible(text):
    """Drop what takes no space, and compose what is left.

    moly.hu writes a zero-width space into its own titles, right after the
    leading article, so a title that has been through a library once may carry
    it; accents may arrive decomposed as well. Neither is visible, and both
    make an otherwise identical string compare - and search - as a different
    one.
    """
    composed = unicodedata.normalize("NFC", text or "")
    return "".join(c for c in composed if unicodedata.category(c) != "Cf")


def fold(text):
    """Strip a title down to what two spellings of the same book share.

    Accents are removed as well as case, so a title that lost its diacritics
    somewhere still compares equal.
    """
    stripped = unicodedata.normalize("NFKD", strip_invisible(text))
    return "".join(c for c in stripped if not unicodedata.combining(c)).casefold()


def title_tokens(text):
    """The set of words in a title, ignoring case, accents and punctuation."""
    return {word for word in re.split(r"\W+", fold(text), flags=re.UNICODE) if word}


def title_forms(text):
    """The word sets a title may be recognised by, the whole title first."""
    return [
        tokens
        for tokens in (title_tokens(fragment) for fragment in title_fragments(text))
        if tokens
    ]


def title_match_kind(page_title, library_title):
    """How a moly.hu title and a library one agree, or None if they do not.

    ``"whole"`` - both say the same thing. Word sets are compared rather than
    strings, because a translated edition carries the Hungarian and the
    original title alike and the two sides agree on neither the order nor the
    separator: the library may hold "Mégis egymásnak teremtve? - So Not Meant
    To Be" where moly.hu has "So Not Meant To Be – Mégis egymásnak teremtve?".

    ``"fragment"`` - one side spells the title out where the other keeps only a
    part of it: the page's "Spiral – Kicsúszás" against the library's plain
    "Kicsúszás", or the page's "A pénz istenei" against the library's "A pénz
    istenei: A Wall Street összeesküvése Amerika leigázására". Only a whole
    title is ever matched against a part - two parts are never compared with
    each other, or "Aliens: Föld ostroma" would match "Aliens: A végső háború".
    Being the looser of the two, it is worth a second opinion from the caller,
    the author's name being the obvious one.
    """
    page_forms = title_forms(page_title)
    library_forms = title_forms(library_title)
    if not page_forms or not library_forms:
        return None
    if page_forms[0] == library_forms[0]:
        return "whole"
    if page_forms[0] in library_forms or library_forms[0] in page_forms:
        return "fragment"
    return None


def _name_forms(names):
    """Each name as its set of words, initials left out.

    A single letter is dropped so that "Raymond E. Feist" and "Raymond Feist"
    still describe the same person.
    """
    forms = []
    for name in names or []:
        words = frozenset(word for word in re.split(r"\W+", fold(name)) if len(word) > 1)
        if words:
            forms.append(words)
    return forms


def authors_overlap(page_authors, library_authors):
    """Do the two sides name an author in common?

    A name is compared as a set of words, so a different order - moly.hu writes
    "Bal Khabra" where a library may hold "Khabra, Bal" - still counts, and one
    name being contained in the other is enough, for the fuller spelling is as
    likely to be on either side. An empty side leaves the question
    unanswerable, which is not the same as a no: nothing is turned down for the
    want of a name.
    """
    page_forms = _name_forms(page_authors)
    library_forms = _name_forms(library_authors)
    if not page_forms or not library_forms:
        return True
    return any(
        page <= library or library <= page
        for page in page_forms
        for library in library_forms
    )


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


def book_url_for_id(moly_id):
    return f"{BOOK_URL}/{moly_id}"


def statistics_url_for_id(moly_id):
    return f"{book_url_for_id(moly_id)}/{STATISTICS_PATH}"


def book_for_id(moly_id, fetch_page_content):
    """The parsed book page of a moly.hu id, or None where there is no page."""
    book_page = fetch_page_content(book_url_for_id(moly_id))
    if book_page:
        return Book(xml_root=parse_page(book_page), moly_id=moly_id)
    return None


def book_page_urls_from_search_page(xml_root):
    """The moly.hu ids of a search page's hits, in the order the page lists them.

    The order is moly.hu's own ranking, best match first, and it is kept: a
    caller that can only afford to open a few of the hits wants the first ones,
    not an arbitrary few. A book listed twice is reported once.
    """
    book_url_prefix = "/konyvek/"
    # Only the genuine search results live inside the "search_area" container.
    # The same "book_selector" class is reused by sidebar widgets (newest
    # releases, recommendations, ...) that every moly.hu page renders. Scoping
    # to "search_area" keeps those out, so a search with no real hits returns
    # nothing instead of unrelated widget books.
    #
    # Both classes are matched as one of possibly several, not as the whole
    # attribute: a second class added on moly.hu's side would otherwise empty
    # every search at once, and silently.
    book_list_root = xml_root.xpath(
        '//div[contains(concat(" ", normalize-space(@class), " "), " search_area ")]'
        '//a[contains(concat(" ", normalize-space(@class), " "), " book_selector ")]'
    )
    matches = []
    for book_item in book_list_root:
        for url in book_item.xpath("@href"):
            if url.startswith(book_url_prefix):
                matches.append(url[len(book_url_prefix) :])
    return list(dict.fromkeys(matches))


# The name the function was first published under, kept for anyone who
# imported it before the typo was noticed.
book_page_urls_from_seach_page = book_page_urls_from_search_page


def search_url(keyword):
    """The moly.hu search page for a keyword.

    The keyword is cleaned before it is quoted. It is built from a library's
    title, and an invisible character or a decomposed accent survives
    quote_plus as a perfectly valid escape that moly.hu then matches against
    nothing.
    """
    query = " ".join(strip_invisible(keyword).split())
    return f"{DOMAIN}/kereses?utf8=%E2%9C%93&query=" + quote_plus(query)


def search(keyword, fetch_page_content):
    """The ids of the books a moly.hu search finds, best match first.

    A fetcher that answers a failed request with nothing gets no hits back
    rather than an error.
    """
    content = fetch_page_content(search_url(keyword))
    if not content:
        return []
    return book_page_urls_from_search_page(parse_page(content))


# How many search hits are opened before giving up on a book. moly.hu answers
# a title search with everything by the author, so the first hit is routinely
# the wrong book. The hits come in moly.hu's order, best match first, so the
# budget goes on the likeliest ones.
CANDIDATE_BUDGET = 6


def is_match(book, info):
    """Is this moly.hu page really the book a library describes?

    ``info`` is the library's record as a dict of ``title``, ``authors`` and
    ``identifiers`` (``isbn`` among them). Nothing should be written off a
    page unless this says yes: a search answers with the whole back catalogue
    of the author, typically, so picking a hit without checking would file
    another book's data.

    An ISBN settles it on its own. Failing that the titles have to agree, in
    one of the two ways ``title_match_kind`` tells apart, and where they agree
    on no more than a part of the title the authors have to bear it out: a
    search for a bare title is answered with every book whose title carries
    the word, and the part a translated book shares with the library can be a
    common enough word on its own - "Kicsúszás" is.
    """
    isbn = normalise_isbn((info.get("identifiers") or {}).get("isbn"))
    # Every edition of the page is compared, not just the one the data is read
    # from: the page's values come off the ebook edition where there is one,
    # while the library may hold the paperback, and the two ISBNs differ
    # although both name this book. Both sides are spelt the same way first,
    # so that hyphens or a lower-case x in the library's number do not matter.
    if isbn:
        if any(isbn == normalise_isbn(candidate) for candidate in (book.isbns() or [])):
            return True
    kind = title_match_kind(book.title(), info.get("title"))
    if kind is None:
        return False
    if kind == "fragment":
        return authors_overlap(book.authors(), info.get("authors"))
    return True


def find_book(info, log, fetch_page, abort=None):
    """Locate the book ``info`` describes on moly.hu and return it, or None.

    ``log`` takes one line of text at a time; ``fetch_page`` answers a URL
    with the page or raises; ``abort`` is checked between pages when given.

    The parsed page is returned rather than any one field of it, so that the
    caller can log what was actually matched - which page a value came from
    is the first thing worth knowing when a result looks wrong.
    """
    moly_id = (info.get("identifiers") or {}).get(MOLY_ID_KEY)
    if moly_id:
        # A moly.hu id is already an identified match, so it is trusted.
        log("Hit URL: %s" % book_url_for_id(moly_id))
        return book_for_id(moly_id, fetch_page)

    terms = generate_search_terms(
        info.get("title"), info.get("authors"), info.get("identifiers") or {}
    )
    log("Search terms: %s" % terms)

    seen = set()
    budget = CANDIDATE_BUDGET
    for term in terms:
        if budget <= 0 or (abort is not None and abort.is_set()):
            break
        log("Search for: %s" % term)
        log("Search URL: %s" % search_url(term))
        try:
            hits = search(term, fetch_page)
        except Exception as err:
            log("Search failed: %s" % err)
            continue
        log("%d search hit(s): %s" % (len(hits), ", ".join(hits) or "-"))
        for candidate in hits:
            if abort is not None and abort.is_set():
                break
            if budget <= 0:
                # The budget is spent across all the terms together, not per
                # term, so it can run out with hits still on the list.
                log(
                    "Candidate budget of %d spent, the rest of the hits go "
                    "unopened" % CANDIDATE_BUDGET
                )
                break
            if candidate in seen:
                continue
            seen.add(candidate)
            budget -= 1
            try:
                book = book_for_id(candidate, fetch_page)
            except Exception as err:
                # One page that will not load is no reason to give up on the
                # rest of the hits.
                log("No page for %s: %s" % (candidate, err))
                continue
            if book and is_match(book, info):
                log("Hit URL: %s" % book_url_for_id(candidate))
                return book
            if book is None:
                log("No page for %s" % candidate)
            else:
                log(
                    'Not this book: %s is "%s" by %s'
                    % (
                        candidate,
                        book.title() or "",
                        " & ".join(book.authors() or []) or "?",
                    )
                )
    # Which of the two ways the search came to nothing is the first thing worth
    # knowing, and "Found 0 results" on its own does not say.
    if not seen:
        log("No search hit for any of the terms")
    else:
        log('None of the %d page(s) opened is "%s"' % (len(seen), info.get("title") or ""))
    return None


# The series link of a book page: "(A Résháború 1.)", "(Aliens 6-7.)" for an
# omnibus, "(Sorozat 1,5.)" for a half volume. The name is everything before
# the last run of numbers.
SERIES_PATTERN = re.compile(r"^\((?P<name>.+?)\s+(?P<index>\d+)(?:[-–,.]\d+)*\.?\)$")

# The language of a book is one of its tags, "angol nyelvű" for one written in
# English, keyed here as moly.hu spells the tag and valued with the ISO 639-1
# code calibre and calibre-web expect.
LANGUAGE_TAG_SUFFIX = "nyelvű"
LANGUAGE_TAGS = {
    "magyar nyelvű": "hu",
    "angol nyelvű": "en",
    "német nyelvű": "de",
    "francia nyelvű": "fr",
    "olasz nyelvű": "it",
    "spanyol nyelvű": "es",
    "portugál nyelvű": "pt",
    "orosz nyelvű": "ru",
    "ukrán nyelvű": "uk",
    "lengyel nyelvű": "pl",
    "cseh nyelvű": "cs",
    "szlovák nyelvű": "sk",
    "román nyelvű": "ro",
    "horvát nyelvű": "hr",
    "szerb nyelvű": "sr",
    "szlovén nyelvű": "sl",
    "bolgár nyelvű": "bg",
    "görög nyelvű": "el",
    "török nyelvű": "tr",
    "holland nyelvű": "nl",
    "svéd nyelvű": "sv",
    "norvég nyelvű": "no",
    "dán nyelvű": "da",
    "finn nyelvű": "fi",
    "észt nyelvű": "et",
    "lett nyelvű": "lv",
    "litván nyelvű": "lt",
    "latin nyelvű": "la",
    "héber nyelvű": "he",
    "arab nyelvű": "ar",
    "perzsa nyelvű": "fa",
    "kínai nyelvű": "zh",
    "japán nyelvű": "ja",
    "koreai nyelvű": "ko",
    "eszperantó nyelvű": "eo",
}

# The paragraph moly.hu puts in front of a blurb that gives the plot away.
SPOILER_WARNING = "Vigyázat! Cselekményleírást tartalmaz."


def paragraph_text(paragraph):
    """The text of a paragraph, inline markup and all, one line per <br>.

    Reading the direct text nodes alone, as an XPath text() does, drops every
    word set in italics or linked and leaves a break where it stood; the
    paragraph is walked instead, so that "a <em>varázsló</em> inasa" reads as
    the three words it is.
    """
    parts = [paragraph.text or ""]
    for child in paragraph:
        # A comment has a function for a tag; its text is not the page's.
        if isinstance(child.tag, str):
            parts.append("\n" if child.tag == "br" else "".join(child.itertext()))
        parts.append(child.tail or "")
    lines = (" ".join(line.split()) for line in "".join(parts).split("\n"))
    return "\n".join(line for line in lines if line)


# FIXME(crash): add isvalid() method to check the required values (id, isbn, title etc.)
class Book:
    """A parsed moly.hu book page.

    The getters read the page each time they are asked, except for the parts
    several of them share - the edition nodes, the schema.org block, the tags -
    which are read once per instance and kept. A page is never modified after
    parsing, so nothing kept can go stale.
    """

    def __init__(self, xml_root, moly_id=None):
        self._xml_root = xml_root
        self._moly_id = moly_id

    def __str__(self) -> str:
        authors = self.authors()
        author = authors[0] if authors else "Unknown"
        series = self.series()
        series_text = f" [{series[0]} / {series[1]}]" if series else ""
        # The edition the data was read from is named, so that a run from the
        # command line shows which of a book's editions answered.
        edition = "ekönyv" if self.is_ebook() else "nyomtatott"
        return (
            f"{author}: {self.title()}{series_text} ({self.publisher()}, "
            f"{self.publication_date()}, {self.isbn()}, {edition}, {self.moly_id()})"
        )

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
            # moly.hu writes a zero-width space (U+200B) into its titles right
            # after the leading article. strip_invisible drops it along with
            # anything else that takes no space, and composes a decomposed
            # accent, so that the title compares equal to the same title typed.
            return strip_invisible(title_node[0]).strip() or None
        return None

    def series(self):
        """The series and the book's place in it as ``(name, index)``, or None.

        The series link reads "(A Résháború 1.)" and is named by its href, the
        /sorozatok/ link of the header: the "action" class it carries is shared
        with the link to the edition list, which would be read instead on a
        page that has one and no series. An omnibus is listed as "(Aliens
        6-7.)" and calibre needs a single integer, so the first number of a
        range is taken. A book in a series without a number - the link then
        reads the bare series name - is not reported, for calibre has no
        index to file it under.
        """
        texts = self._xml_root.xpath(
            '//*[@id="content"]//a[starts-with(@href, "/sorozatok/")]/text()'
        ) or self._xml_root.xpath(
            # Older layouts, where the series link has no href of its own.
            '//*[@id="content"]'
            '//*[contains(concat(" ", normalize-space(@class), " "), " action ")]'
            "/text()"
        )
        if not texts:
            return None
        match = SERIES_PATTERN.match(" ".join(str(texts[0]).split()))
        if not match:
            return None
        return match.group("name"), int(match.group("index"))

    @cached_property
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

    @cached_property
    def _editions(self):
        """The editions of the block the first one sits in.

        An edition rendered inside a review further down the page is a copy of
        one of these, so it is left out rather than counted twice.
        """
        editions = self._edition_nodes
        if not editions:
            return []
        block = editions[0].getparent()
        return [edition for edition in editions if edition.getparent() is block]

    @cached_property
    def _primary_edition(self):
        """The edition the metadata describes.

        The ebook edition is preferred where the page has one, because that is
        the edition a calibre library actually holds: its ISBN and publication
        date are its own, and filing the printed edition's ISBN against an
        epub is simply wrong. Where no edition is marked as an ebook the first
        one is used.
        """
        editions = self._editions
        for edition in editions:
            if is_ebook_edition(edition):
                return edition
        return editions[0] if editions else None

    @cached_property
    def _fill_in_editions(self):
        """The editions that may fill in what the primary one leaves out.

        Hungarian ebook editions are thinly documented: the line often carries
        a bare year where the printed edition has a full "Megjelenés
        időpontja" tooltip, and it can omit the publisher, the translator or
        even the ISBN. Those are the same book, so the printed editions stand
        in for what the ebook line does not state.

        This is only done for an ebook. On a page whose editions are all
        printed, the first one is read on its own as before - a book with an
        old and a re-translated edition must not end up with the year of one
        and the translator of another.

        The editions of the same publisher come first, being the most likely
        to describe the same release; the rest follow in page order.
        """
        primary = self._primary_edition
        if primary is None or not is_ebook_edition(primary):
            return []
        publisher = (self._edition_publisher(primary) or "").strip().lower()

        def same_publisher(edition):
            name = (self._edition_publisher(edition) or "").strip().lower()
            return bool(publisher) and name == publisher

        others = [e for e in self._editions if e is not primary]
        return sorted(others, key=lambda edition: 0 if same_publisher(edition) else 1)

    def _from_editions(self, reader):
        """A field off the primary edition, or off the ones filling in for it."""
        primary = self._primary_edition
        value = reader(primary) if primary is not None else None
        if value is not None:
            return value
        for edition in self._fill_in_editions:
            value = reader(edition)
            if value is not None:
                return value
        return None

    def is_ebook(self):
        """Whether the edition the data is read from is an ebook."""
        return is_ebook_edition(self._primary_edition)

    def publisher(self):
        return self._from_editions(self._edition_publisher)

    def _edition_publisher(self, edition):
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
        """When the edition was published, as precisely as the page says.

        An ebook line usually states a bare year while the printed edition of
        the same year carries the day in its tooltip. The precise date is the
        same book's, so it is taken - but only where it agrees with the ebook
        on every part the ebook states, so that a 2017 ebook can never be
        given a 2015 hardback's day.
        """
        primary = self._primary_edition
        best, best_precision = (
            self._edition_publication_date(primary)
            if primary is not None
            else (None, None)
        )
        for edition in self._fill_in_editions:
            candidate, candidate_precision = self._edition_publication_date(edition)
            if candidate is None:
                continue
            if best is None:
                # The ebook line states no date at all, so the printed
                # editions are all there is to go on.
                best, best_precision = candidate, candidate_precision
            elif sharpens(candidate, candidate_precision, best, best_precision):
                best, best_precision = candidate, candidate_precision
        return best

    def _edition_publication_date(self, edition):
        """An edition's publication date as ``(date, precision)``."""
        if edition is None:
            return None, None
        # The edition line exposes the full publication date in the tooltip of
        # the "Megjelenés időpontja:" abbreviation, e.g.
        # <abbr title="Megjelenés időpontja: 2025. szeptember 4.">2025</abbr>.
        for title in edition.xpath(".//abbr/@title"):
            if "Megjelenés időpontja" in title:
                date, precision = parse_hungarian_date_precision(title)
                if date:
                    return date, precision
        # Editions that only expose a bare year on the edition line (older
        # layouts where the year is plain text, and ebook lines, which rarely
        # carry the tooltip at all). The year stands on the publisher line -
        # "Szukits, Szeged, 2019", the line holding the /kiadok/ link - so that
        # line is read first, and the rest of the edition only after it for
        # the layouts that put the year elsewhere. A page count is left out
        # either way, so "1024 oldal" on the next line can never stand in for
        # a missing year.
        publisher_lines = edition.xpath('.//div[a[starts-with(@href, "/kiadok/")]]')
        for node in publisher_lines + [edition]:
            for text in node.xpath(".//text()"):
                year = bare_year(text)
                if year:
                    return datetime.date(year, 1, 1), YEAR_PRECISION
        return None, None

    def isbn(self):
        """The ISBN of the edition the metadata describes.

        The ebook edition's own number where its line states one. moly.hu
        often leaves it off, and the printed edition's is then reported rather
        than nothing at all - a record with the paperback's ISBN still names
        the book, where a record with none names nothing.
        """
        return self._from_editions(self._edition_isbn)

    def isbns(self):
        """The ISBN of every edition listed, in page order, or None.

        A library holding the paperback and a page whose data is read off the
        ebook edition still describe the same book, so a caller confirming a
        match by ISBN has to be able to see all of them.
        """
        found = []
        for edition in self._edition_nodes:
            isbn = self._edition_isbn(edition)
            if isbn and isbn not in found:
                found.append(isbn)
        return found or None

    def _edition_isbn(self, edition):
        if edition is None:
            return None
        # The number is the text right behind the "ISBN" label:
        #   <strong>ISBN</strong>: 9789635511235
        # Taking it from there keeps a page count or a cover id from being
        # read as an ISBN.
        for label in edition.xpath('.//strong[starts-with(normalize-space(), "ISBN")]'):
            match = ISBN_PATTERN.search(label.tail or "")
            if match:
                return match.group(1).upper()
        for text in edition.xpath(".//text()"):
            match = ISBN_PATTERN.search(text)
            if match:
                return match.group(1).upper()
        return None

    def translator(self):
        return self._from_editions(self._edition_translator)

    def _edition_translator(self, edition):
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
        hrefs = self._xml_root.xpath(
            '//*[contains(concat(" ", normalize-space(@class), " "), " coverbox ")]'
            "//a/@href"
        )
        # The page links the cover relative to the site; an absolute URL is
        # passed through as it stands rather than prefixed a second time.
        urls = [
            href if href.startswith("http") else f"{DOMAIN}{href}"
            for href in hrefs
            if href
        ]
        return urls or None

    @cached_property
    def _tag_list(self):
        tags_node = (
            self._xml_root.xpath('//*[@id="tags"]//*[@class="hover_link"]/text()')
            or self._xml_root.xpath(
                '//*[@id="book_tags"]//*[@class="hover_link"]/text()'
            )
            or self._xml_root.xpath('//*[@id="book_tags"]//*[@rel="tag"]/text()')
        )
        tags = (" ".join(str(text).split()) for text in tags_node)
        return list(dict.fromkeys(tag for tag in tags if tag))

    def tags(self):
        return list(self._tag_list) or None

    @cached_property
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
        """The score as calibre's whole stars, 0 to 5, or None.

        A metadata source reports its rating on a 0-5 scale, and calibre
        rounds what the sources answer to a whole star before it is applied,
        so half stars cannot reach the library this way; the Moly.hu
        Translator keeps the percentage itself for a column of its own. The
        rounding is done here, half up, rather than left to calibre's
        round(), which rounds a tie to the even number and made 90% four
        stars and 50% two.
        """
        percent = self.rating_percent()
        if percent is None:
            return None
        return int(percent / 20 + 0.5)

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
        stated = (self._aggregate_rating or {}).get("ratingValue")
        # Only taken when it is written as a percentage. schema.org means
        # ratingValue to be a score out of bestRating, so a day when moly.hu
        # makes the field conform would otherwise turn a 4.5 into 4.5%. The
        # header still shows the percentage and is read instead.
        if stated is not None and "%" in str(stated):
            percent = parse_decimal(stated)
            if percent is not None:
                return percent
        return parse_decimal(self._rating_percent_text())

    @cached_property
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
        stated = (self._aggregate_rating or {}).get("ratingCount")
        if stated is not None:
            count = parse_count(stated)
            if count is not None:
                return count
        link = self._statistic_link
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
        link = self._statistic_link
        href = link.get("href") if link is not None else None
        if href:
            return href if href.startswith("http") else DOMAIN + href
        if self._moly_id and (
            self.rating_count() is not None or self.rating_percent() is not None
        ):
            return statistics_url_for_id(self._moly_id)
        return None

    def languages(self):
        """The ISO 639-1 codes of the languages the book's tags name, or None.

        moly.hu tags a book "angol nyelvű" when it is written in English and
        leaves a Hungarian one untagged as often as not, so tags that name no
        language read as Hungarian. A language tag that is not in the table is
        another matter: the book is then known not to be Hungarian, and nothing
        is claimed rather than the wrong thing. A page without tags has nothing
        to say either way.
        """
        tags = self.tags()
        if not tags:
            return None
        codes = []
        unknown_language = False
        for tag in tags:
            name = tag.lower()
            code = LANGUAGE_TAGS.get(name)
            if code is not None:
                if code not in codes:
                    codes.append(code)
            elif name.endswith(" " + LANGUAGE_TAG_SUFFIX):
                unknown_language = True
        if codes:
            return codes
        return None if unknown_language else ["hu"]

    def description(self):
        """The blurb, one paragraph per line, or None.

        The spoiler warning moly.hu puts in front of a blurb that gives the
        plot away sits in a paragraph of its own, in a block of the same class
        as the blurb, so it is left out by name.
        """
        text_class = 'contains(concat(" ", normalize-space(@class), " "), " text ")'
        paragraphs = self._xml_root.xpath(
            f'//*[@id="content"]//*[@id="full_description" and {text_class}]/p'
        ) or self._xml_root.xpath(f'//*[@id="content"]//*[{text_class}]/p')
        lines = []
        for paragraph in paragraphs:
            if "spoiler" in (paragraph.get("class") or "").split():
                continue
            text = paragraph_text(paragraph)
            if text and text != SPOILER_WARNING:
                lines.append(text)
        return "\n".join(lines) or None
