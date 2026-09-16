from queue import Empty, Queue
import datetime

from calibre.utils.date import utc_tz
from calibre.utils.cleantext import clean_ascii_chars
from calibre.ebooks.metadata.sources.base import Source, Option
from calibre.ebooks.metadata.book.base import Metadata
from calibre.ebooks.metadata import check_isbn

import calibre_plugins.moly_hu_reloaded.moly_hu as moly_hu

# How long to wait for a moly.hu page, in seconds, when calibre states no
# timeout of its own.
FETCH_TIMEOUT = 30


def book_to_metadata(book, relevance=0) -> Metadata:
    metadata = Metadata(book.title(), book.authors())
    # The book's place among the results, which is moly.hu's own ranking of
    # its search hits, so that calibre can break a tie between two records
    # with it.
    metadata.source_relevance = relevance
    metadata.set_identifier(moly_hu.MOLY_ID_KEY, book.moly_id())
    metadata.set_identifier('isbn', check_isbn(book.isbn()))
    metadata.comments = book.description()
    metadata.tags = book.tags() or []
    metadata.languages = book.languages() or []
    metadata.publisher = book.publisher()
    if pubdate := book.publication_date():
        # Build a timezone-aware datetime: calibre converts naive pubdates
        # through the local timezone, which can shift the stored date by a day.
        metadata.pubdate = datetime.datetime(
            pubdate.year, pubdate.month, pubdate.day, tzinfo=utc_tz
        )
    rating = book.rating()
    # A zero is a score too: 0% off sixty ratings is not the absence of one.
    if rating is not None:
        metadata.rating = rating
    series = book.series()
    if series:
        metadata.series, metadata.series_index = series
    return metadata


class Molyhu(Source):
    name = 'Moly.hu Reloaded'
    description = _('Downloads metadata and covers from moly.hu. Based on Hokutya Moly_hu plugin.')
    author = 'Imre NAGY'
    version = (0, 0, 0)
    minimum_calibre_version = (5, 0, 0)

    MOLY_ID_KEY = moly_hu.MOLY_ID_KEY

    # Capabilities
    capabilities = frozenset(['identify', 'cover'])
    touched_fields = frozenset([
        'title',
        'authors',
        'identifier:isbn',
        f'identifier:{MOLY_ID_KEY}',
        'tags',
        'comments',
        'rating',
        'series',
        'series_index',
        'publisher',
        'pubdate',
        'languages',
    ])

    # Options
    KEY_MAX_BOOKS = 'max_books'
    options = (
        Option(KEY_MAX_BOOKS, 'number', 3, _('Maximum number of books to get'), _('The maximum number of books to process from the moly.hu search result')),
    )

    def identify(self, log, result_queue, abort, title, authors, identifiers, timeout):
        max_books = self.prefs[self.KEY_MAX_BOOKS]

        # Normalise the query with calibre's tokenizers, which drop leading
        # articles, punctuation and ZWJ noise that can throw off moly.hu's
        # search. The cleaned values are fed into the same term-builder so the
        # ISBN -> author+title -> title fallback order is preserved.
        #
        # The title is handed over raw and tokenized by the callback instead,
        # because the term-builder first splits it at the colon or dash that
        # moly.hu turns into a subtitle - and get_title_tokens replaces exactly
        # that punctuation with a space, leaving nothing to split on.
        clean_authors = (
            [' '.join(self.get_author_tokens(authors, only_first_author=True))]
            if authors
            else authors
        )
        search_terms = moly_hu.generate_search_terms(
            title, clean_authors, identifiers,
            normalise_title=lambda text: ' '.join(self.get_title_tokens(text)),
        )
        log.info(f'Search terms: {search_terms}')

        def fetch_page(url):
            return self._fetch_page(url, timeout)

        # The moly.hu id names the book outright, so it goes first. Every hit
        # is kept once, in the order it was found - moly.hu's own ranking - so
        # that a book the ISBN search and the title search both return is not
        # fetched twice, nor counted twice against max_books.
        book_ids = []
        moly_id = identifiers.get(self.MOLY_ID_KEY)
        if moly_id:
            book_ids.append(moly_id)

        for search_term in search_terms:
            if len(book_ids) >= max_books:
                break
            if abort.is_set():
                log.info('Abort request received, returning.')
                return
            log.info(f'Search for: {search_term}')
            try:
                hits = moly_hu.search(search_term, fetch_page)
            except Exception as err:
                # One search that fails must not cost the run the others.
                log.exception(f'Search for "{search_term}" failed: {err}')
                continue
            book_ids = list(dict.fromkeys(book_ids + list(hits)))

        if len(book_ids) > max_books:
            log.info(f'{len(book_ids)} hits, the first {max_books} are fetched. (limit: {max_books})')

        for index, moly_id in enumerate(book_ids[:max_books]):
            if abort.is_set():
                log.info('Abort request received, returning.')
                return
            try:
                book = moly_hu.book_for_id(moly_id, fetch_page)
            except Exception as err:
                # A stale identifier or a transient error loses this book
                # alone, not every other hit with it.
                log.exception(f'Failed to fetch the page of {moly_id}: {err}')
                continue
            if not book:
                log.warning(f'No book found with id {moly_id}')
                continue
            if covers := book.cover_urls():
                self.cache_identifier_to_cover_url(book.moly_id(), covers[0])
            # Every edition's ISBN is cached, not just the one the metadata
            # is read from: the record carries the ebook edition's ISBN where
            # the page has one, and a search made with the paperback's ISBN
            # still has to find its way back to this book.
            for isbn in (book.isbns() or []):
                self.cache_isbn_to_identifier(isbn, book.moly_id())

            metadata = book_to_metadata(book, relevance=index)
            self.clean_downloaded_metadata(metadata)
            result_queue.put(metadata)

        return None

    def _fetch_page(self, url, timeout=FETCH_TIMEOUT):
        br = self.browser
        response = br.open_novisit(url, timeout=timeout or FETCH_TIMEOUT)
        raw = response.read().strip()
        raw = raw.decode('utf-8', errors='replace')
        return clean_ascii_chars(raw)

    def get_book_url(self, identifiers):
        """The book's moly.hu page, as the single (type, value, url) triple
        calibre asks a source for."""
        moly_id = identifiers.get(self.MOLY_ID_KEY)
        if moly_id:
            return (self.MOLY_ID_KEY, moly_id, moly_hu.book_url_for_id(moly_id))
        return None

    # The ISBN is deliberately not claimed: a source that returns a URL for
    # an identifier type takes that link over from calibre for every book in
    # the library, and calibre's own ISBN link is a live catalogue.

    def get_book_url_name(self, idtype, idval, url):
        return 'moly.hu'

    def get_cached_cover_url(self, identifiers):
        moly_id = identifiers.get(self.MOLY_ID_KEY)
        if not moly_id:
            isbn = identifiers.get('isbn')
            moly_id = self.cached_isbn_to_identifier(isbn)
        return self.cached_identifier_to_cover_url(moly_id)

    # original from: calibre/src/calibre/ebooks/metadata/sources/amazon.py
    def download_cover(self, log, result_queue, abort, title=None, authors=None, identifiers=None, timeout=30, get_best_cover=False):
        identifiers = identifiers or {}
        cached_url = self.get_cached_cover_url(identifiers)
        if cached_url is None:
            log.info('No cached cover found, running identify')
            rq = Queue()
            self.identify(log, rq, abort, title=title, authors=authors, identifiers=identifiers, timeout=timeout)
            if abort.is_set():
                return
            results = []
            while True:
                try:
                    results.append(rq.get_nowait())
                except Empty:
                    break
            results.sort(key=self.identify_results_keygen(title=title, authors=authors, identifiers=identifiers))
            for mi in results:
                cached_url = self.get_cached_cover_url(mi.identifiers)
                if cached_url is not None:
                    break
        if cached_url is None:
            log.info('No cover found')
            return

        if abort.is_set():
            return

        log('Downloading cover from:', cached_url)
        try:
            br = self.browser
            cdata = br.open_novisit(cached_url, timeout=timeout).read()
            result_queue.put((self, cdata))
        except Exception:
            log.exception('Failed to download cover from:', cached_url)
