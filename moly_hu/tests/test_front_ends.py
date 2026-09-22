"""The calibre and calibre-web front ends, run against stand-ins for the hosts.

Neither calibre nor calibre-web can be imported here, so the few modules of
theirs the front ends import are stood in for with the least the code under
test touches, for as long as it takes to load the front ends. What is tested
is the front ends' own logic: how a record is built from a page, how hits are
collected and capped, what a page that will not load costs, how a value is
shaped for a column.

The metadata source is loaded as the package calibre makes of its zip, with the
scraper next to it, because how it imports the scraper is part of what is
tested: calibre installs a new version over a loaded one by running the
package again, and the scraper it finds then has to be the new one.
"""
import contextlib
import datetime
import importlib
import importlib.util
import queue
import sys
import threading
import types
from pathlib import Path

import moly_hu.moly_hu as scraper

REPO = Path(__file__).resolve().parents[2]
# The metadata source's package name in calibre, and the directory that plays
# the part of its zip: the scraper sits there as moly_hu.py, as in the zip.
RELOADED = "calibre_plugins.moly_hu_reloaded"
SCRAPER_DIR = REPO / "moly_hu" / "src" / "moly_hu"
INPUTS = Path(__file__).parent / "inputs"
FEIST_ID = "raymond-e-feist-az-erzoszivu-magus"
BOB_ID = "dennis-e-taylor-mi-bob"
EBOOK_MARKER = "\U0001F4F1"


def page_for(url):
    """The fixture that stands for a moly.hu URL; anything else is a 404."""
    if "/kereses?" in url:
        return (INPUTS / "search_page_raymond_feist.htm").read_bytes()
    if url == scraper.book_url_for_id(FEIST_ID):
        return (INPUTS / "book_page_raymond_feist_az_erzoszivu_magus.htm").read_bytes()
    if url == scraper.book_url_for_id(BOB_ID):
        return (INPUTS / "book_page_dennis_e_taylor_mi_bob.htm").read_bytes()
    raise OSError("HTTP 404 " + url)


class Log:
    """calibre's job log and calibre-web's logger, as far as they are used."""

    def __init__(self):
        self.lines = []

    def __call__(self, *args, **kwargs):
        self.lines.append(" ".join(str(arg) for arg in args))

    info = warning = error = exception = __call__


class FakeResponse:
    def __init__(self, data):
        self.content = data

    def read(self):
        return self.content

    def raise_for_status(self):
        pass


class FakeBrowser:
    """calibre's mechanize browser: records every (url, timeout) it is asked for."""

    def __init__(self):
        self.calls = []

    def open_novisit(self, url, timeout=None):
        self.calls.append((url, timeout))
        return FakeResponse(page_for(url))

    open = open_novisit


BROWSERS = []  # every browser the translator action creates


def new_browser(*args, **kwargs):
    BROWSERS.append(FakeBrowser())
    return BROWSERS[-1]


REQUESTS = []  # every (url, timeout) the calibre-web provider asks requests for


def requests_get(url, headers=None, timeout=None):
    REQUESTS.append((url, timeout))
    return FakeResponse(page_for(url))


class Metadata:
    """calibre's Metadata, as far as book_to_metadata sets it."""

    def __init__(self, title, authors):
        self.title, self.authors, self.identifiers = title, authors, {}

    def set_identifier(self, typ, val):
        if val:
            self.identifiers[typ] = val
        else:
            self.identifiers.pop(typ, None)


class Source:
    """calibre's metadata Source base, as far as the plugin relies on it."""

    prefs = {"max_books": 3}

    def __init__(self):
        self.browser = FakeBrowser()
        self.covers, self.isbns = {}, {}

    def get_author_tokens(self, authors, only_first_author=True):
        return authors[0].split()

    def get_title_tokens(self, title):
        return title.split()

    def cache_identifier_to_cover_url(self, moly_id, url):
        self.covers[moly_id] = url

    def cache_isbn_to_identifier(self, isbn, moly_id):
        self.isbns[isbn] = moly_id

    def cached_isbn_to_identifier(self, isbn):
        return self.isbns.get(isbn)

    def cached_identifier_to_cover_url(self, moly_id):
        return self.covers.get(moly_id)

    def clean_downloaded_metadata(self, mi):
        pass

    def get_book_urls(self, identifiers):
        # calibre's own: the plural wraps the single triple.
        data = self.get_book_url(identifiers)
        return () if data is None else (data,)


class MetaRecord:
    """calibre-web's record, as far as book_to_metadata sets it."""

    def __init__(self, id, title, authors, url, source):
        self.id, self.title, self.authors, self.url, self.source = id, title, authors, url, source
        self.identifiers = {}


class MetaSourceInfo:
    def __init__(self, id, description, link):
        self.id = id


class ProviderBase:
    active = True

    def get_title_tokens(self, title, strip_joiners=True):
        return title.split()


STAND_INS = {
    "calibre": {"browser": new_browser},
    "calibre.constants": {"config_dir": "/nonexistent"},
    "calibre.utils": {},
    "calibre.utils.date": {"utc_tz": datetime.timezone.utc},
    "calibre.utils.cleantext": {"clean_ascii_chars": lambda text: text},
    "calibre.ebooks": {},
    "calibre.ebooks.metadata": {"check_isbn": lambda isbn: isbn},
    "calibre.ebooks.metadata.book": {},
    "calibre.ebooks.metadata.book.base": {"Metadata": Metadata},
    "calibre.ebooks.metadata.sources": {},
    "calibre.ebooks.metadata.sources.base": {"Source": Source, "Option": lambda *a, **k: None},
    "calibre.gui2": {"Dispatcher": lambda f: f, "error_dialog": lambda *a, **k: None,
                     "info_dialog": lambda *a, **k: None},
    "calibre.gui2.actions": {"InterfaceAction": type("InterfaceAction", (), {})},
    "calibre.gui2.threaded_jobs": {"ThreadedJob": object},
    "calibre_plugins": {"__path__": []},
    "calibre_plugins.moly_hu_translator": {
        "moly_hu": scraper, "EBOOK_MARKER": EBOOK_MARKER,
        "prefs": {"ebook_marker": EBOOK_MARKER, "translator_column": "#translator",
                  "rating_column": "#moly_rating", "rating_count_column": "#moly_rating_count",
                  "statistics_url_column": "#moly_stats_raw", "type_column": "#type"},
    },
    "calibre_plugins.moly_hu_translator.moly_hu": scraper,
    "requests": {"get": requests_get},
    "cps": {"logger": types.SimpleNamespace(create=Log)},
    "cps.isoLanguages": {"get_lang3": lambda code: code, "get_language_name": lambda locale, code: code},
    "cps.services": {},
    "cps.services.Metadata": {"MetaRecord": MetaRecord, "MetaSourceInfo": MetaSourceInfo,
                              "Metadata": ProviderBase},
    "cps.metadata_provider": {},
    "cps.metadata_provider.moly_hu_provider": scraper,
}


@contextlib.contextmanager
def hosts_stood_in():
    """calibre and calibre-web stood in for while the block runs, and taken
    down again afterwards - the plugin package included - so that nothing
    else sees them."""
    touched = list(STAND_INS) + [RELOADED, RELOADED + ".moly_hu"]
    replaced = {name: sys.modules.get(name) for name in touched}
    for name, attrs in STAND_INS.items():
        if isinstance(attrs, dict):
            module = types.ModuleType(name)
            module.__dict__.update(attrs)
        else:
            module = attrs
        sys.modules[name] = module
    try:
        yield
    finally:
        for name, original in replaced.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def load_reloaded_plugin():
    """The metadata source as calibre loads it out of its zip: the package
    calibre_plugins.moly_hu_reloaded, whose __init__ imports the scraper that
    sits next to it."""
    spec = importlib.util.spec_from_file_location(
        RELOADED, REPO / "calibre" / "__init__.py",
        submodule_search_locations=[str(SCRAPER_DIR)],
    )
    package = importlib.util.module_from_spec(spec)
    package._ = lambda text: text  # calibre injects the translation function
    sys.modules[RELOADED] = package
    spec.loader.exec_module(package)
    return package


def load_front_ends():
    with hosts_stood_in():
        return (
            load_reloaded_plugin(),
            load("moly_hu_translator_action", REPO / "calibre_translator" / "action.py"),
            load("moly_hu_calibreweb_provider", REPO / "calibre-web" / "moly_hu.py"),
        )


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    module._ = lambda text: text  # calibre injects the translation function
    spec.loader.exec_module(module)
    return module


reloaded, action, provider = load_front_ends()


def drain(result_queue):
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())
    return results


def book_from(url, moly_id):
    return scraper.Book(scraper.parse_page(page_for(url)), moly_id)


# ---------------------------------------------------------------- calibre source

def test_book_to_metadata_reads_the_ebook_edition():
    mi = reloaded.book_to_metadata(book_from(scraper.book_url_for_id(BOB_ID), BOB_ID), relevance=2)

    assert mi.title == "MI, Bob"
    assert mi.authors == ["Dennis E. Taylor"]
    assert mi.source_relevance == 2
    assert mi.identifiers == {"moly_hu": BOB_ID, "isbn": "9786155628269"}
    assert (mi.series, mi.series_index) == ("Bobiverzum", 1)
    assert mi.rating == 4
    assert mi.pubdate == datetime.datetime(2017, 6, 12, tzinfo=datetime.timezone.utc)
    assert mi.publisher == "Metropolis Media"
    assert mi.languages == ["hu"]
    assert "hard sci-fi" in mi.tags


def test_book_to_metadata_keeps_a_zero_rating_and_sets_lists_not_none():
    html = (
        '<html><head><script type="application/ld+json">{"@type": "Book", '
        '"aggregateRating": {"ratingValue": "0%", "ratingCount": "62"}}</script>'
        '</head><body><div id="content"><span class="fn">Semmi</span></div></body></html>'
    )
    mi = reloaded.book_to_metadata(scraper.Book(scraper.parse_page(html), "x"))

    assert mi.rating == 0
    assert mi.tags == []
    assert mi.languages == []
    assert getattr(mi, "series", None) is None


def test_identify_fetches_each_hit_once_in_order_and_survives_a_dead_page():
    source = reloaded.Molyhu()
    log, results = Log(), queue.Queue()

    source.identify(log, results, threading.Event(), "Az érzőszívű mágus",
                    ["Raymond E. Feist"], {"moly_hu": FEIST_ID}, 12)

    records = drain(results)
    assert [(mi.title, mi.source_relevance) for mi in records] == [("Az érzőszívű mágus", 0)]
    urls = [url for url, timeout in source.browser.calls]
    # The identifier's page comes first and is not fetched again although the
    # search lists it first as well; the other two of max_books=3 have no page
    # here, and losing them does not lose the first.
    assert urls[0].startswith(scraper.DOMAIN + "/kereses?")
    assert urls[1:] == [scraper.book_url_for_id(moly_id) for moly_id in (
        FEIST_ID, "raymond-e-feist-magus-a-tanitvany", "raymond-e-feist-ezusttovis")]
    # calibre's timeout reaches every request.
    assert {timeout for url, timeout in source.browser.calls} == {12}
    assert sum("Failed to fetch the page" in line for line in log.lines) == 2
    assert source.isbns == {"9637519416": FEIST_ID}
    assert source.covers == {FEIST_ID: "https://moly.hu/system/covers/big/covers_4959.jpg?1395344202"}


def test_identify_stops_on_abort():
    source = reloaded.Molyhu()
    abort = threading.Event()
    abort.set()
    results = queue.Queue()

    source.identify(Log(), results, abort, "Bármi", ["Bárki"], {}, 12)

    assert drain(results) == []
    assert source.browser.calls == []


def test_installing_over_a_loaded_version_imports_the_new_scraper():
    # calibre installs a zip over a plugin it has already loaded by running the
    # package's __init__ again and nothing else - zipplugin.py reloads the
    # package, not the modules it imported - so the scraper of the version
    # being replaced is still in sys.modules. 3.2.1 installed over 3.2.0 read
    # a name off it that 3.2.0's scraper did not have, and failed with
    #   AttributeError: module 'calibre_plugins.moly_hu_reloaded.moly_hu'
    #   has no attribute 'MOLY_ID_KEY'
    with hosts_stood_in():
        package = load_reloaded_plugin()
        stale = types.ModuleType(RELOADED + ".moly_hu")  # the old scraper, no MOLY_ID_KEY
        sys.modules[stale.__name__] = stale
        package.moly_hu = stale

        # What importlib.reload does once it has found the package again.
        package.__spec__.loader.exec_module(package)

        assert package.moly_hu is not stale
        assert package.moly_hu is sys.modules[RELOADED + ".moly_hu"]
        assert package.Molyhu.MOLY_ID_KEY == "moly_hu"
        assert "identifier:moly_hu" in package.Molyhu.touched_fields
        assert package.moly_hu.find_book is not None


def test_get_book_url_is_one_triple_and_the_isbn_is_left_to_calibre():
    source = reloaded.Molyhu()

    assert source.get_book_url({"moly_hu": "x"}) == ("moly_hu", "x", "https://moly.hu/konyvek/x")
    assert source.get_book_url({"isbn": "1"}) is None
    assert source.get_book_urls({"moly_hu": "x", "isbn": "1"}) == (("moly_hu", "x", "https://moly.hu/konyvek/x"),)
    assert source.get_book_url_name("moly_hu", "x", "https://moly.hu/konyvek/x") == "moly.hu"
    assert "language" not in source.touched_fields
    assert "languages" in source.touched_fields


# ---------------------------------------------------------- translator action

def test_fetch_book_data_uses_one_browser_and_goes_on_past_a_dead_page():
    BROWSERS.clear()
    log = Log()
    books = {
        1: {"title": "Az érzőszívű mágus", "authors": ["Raymond E. Feist"], "identifiers": {}},
        2: {"title": "MI, Bob", "authors": ["Dennis E. Taylor"], "identifiers": {"moly_hu": BOB_ID}},
        3: {"title": "Sethanon alkonya", "authors": ["Raymond E. Feist"], "identifiers": {}},
    }

    found, missing = action.fetch_book_data(books, log=log)

    assert found[1] == {
        "translator": ["Kaposi Tamás"], "rating": 94.0, "rating_count": 62,
        "statistics_url": "https://moly.hu/konyvek/raymond-e-feist-az-erzoszivu-magus/statisztika",
    }
    assert found[2]["type"] == EBOOK_MARKER
    assert found[2]["translator"] == ["Oszlánszky Zsolt"]
    # Its hits are all pages this site does not have, bar the first, which
    # is another book: the budget runs out and the book is reported missing
    # rather than the run failing.
    assert missing == ["Sethanon alkonya"]
    assert len(BROWSERS) == 1
    assert {timeout for url, timeout in BROWSERS[0].calls} == {action.FETCH_TIMEOUT}
    assert sum(line.startswith("No page for") for line in log.lines) == 5


def test_format_for_column_follows_the_column():
    names, multiple = ["Kaposi Tamás", "Nagy Imre"], {"datatype": "text", "is_multiple": {"ui_to_list": "&"}}

    assert action.format_for_column(names, {"datatype": "text"}) == "Kaposi Tamás, Nagy Imre"
    assert action.format_for_column(names, multiple) == names
    assert action.format_for_column("https://moly.hu/x", {"datatype": "text"}) == "https://moly.hu/x"
    assert action.format_for_column("https://moly.hu/x", multiple) == ["https://moly.hu/x"]
    assert action.format_for_column(94.0, {"datatype": "float"}) == 94.0
    assert action.format_for_column(94.0, {"datatype": "int"}) == 94
    assert action.format_for_column(94.0, {"datatype": "text"}) == "94"
    assert action.format_for_column(62, multiple) == ["62"]
    # A calibre rating column holds half stars, 0-10, rounded half up.
    assert action.format_for_column(94.0, {"datatype": "rating"}) == 9
    assert action.format_for_column(85.0, {"datatype": "rating"}) == 9
    assert action.format_for_column(100.0, {"datatype": "rating"}) == 10


def test_describe_value_reads_as_a_person_would():
    assert action.describe_value(None) == ""
    assert action.describe_value(["A", "B"]) == "A, B"
    assert action.describe_value(94.0) == "94"
    assert action.describe_value(94.5) == "94.5"


# ------------------------------------------------------------- calibre-web

def test_provider_opens_the_first_hits_only_and_survives_a_dead_page():
    REQUESTS.clear()

    records = provider.Molyhu().search("Raymond Feist", locale="en")

    assert [record.title for record in records] == ["Az érzőszívű mágus"]
    assert records[0].identifiers == {"moly_hu": FEIST_ID, "isbn": "9637519416"}
    assert records[0].languages == ["hu"]
    assert (records[0].series, records[0].series_index) == ("A Résháború", 1)
    assert records[0].publishedDate == "1991-01-01"
    assert len(REQUESTS) == 1 + provider.MAX_BOOKS
    assert {timeout for url, timeout in REQUESTS} == {provider.FETCH_TIMEOUT}


def test_provider_record_of_a_page_without_tags_holds_empty_lists():
    book = scraper.Book(scraper.parse_page('<div id="content"><span class="fn">Címtelen</span></div>'), "x")

    record = provider.book_to_metadata(book, provider.Molyhu.MOLY_SOURCE_INFO, "en")

    assert record.title == "Címtelen"
    assert record.languages == []
    assert record.tags == []
    assert record.rating == 0
