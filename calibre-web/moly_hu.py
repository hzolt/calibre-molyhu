from typing import List, Optional

import requests

from cps import logger
from cps.isoLanguages import get_lang3, get_language_name
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata

import cps.metadata_provider.moly_hu_provider as moly_hu


log = logger.create()

# How long to wait for moly.hu, in seconds. requests waits forever by default,
# and calibre-web waits for every provider before it answers a search.
FETCH_TIMEOUT = 15
# How many of the hits are opened. Each is a page of its own, fetched one
# after the other while the search waits, and moly.hu lists the best match
# first, so the first few are the ones worth having.
MAX_BOOKS = 5


def book_to_metadata(book: moly_hu.Book, source_info: MetaSourceInfo, locale) -> MetaRecord:
    metadata = MetaRecord(
        id=book.moly_id(),
        title=book.title() or '',
        authors=book.authors() or ['Unknown'],
        url=moly_hu.book_url_for_id(book.moly_id()),
        source=source_info,
    )

    if covers := book.cover_urls():
        metadata.cover = covers[0]
    metadata.description = book.description() or ''
    series = book.series()
    if series:
        metadata.series, metadata.series_index = series
    metadata.identifiers[source_info.id] = book.moly_id()
    if book.isbn():
        metadata.identifiers['isbn'] = book.isbn()
    metadata.publisher = book.publisher() or ''
    if pubdate := book.publication_date():
        metadata.publishedDate = pubdate.strftime('%Y-%m-%d')
    metadata.rating = book.rating() or 0
    # A page without tags names no language and no tag; the form expects a
    # list either way, and None would fail before anything is shown.
    metadata.languages = parse_languages(book.languages() or [], locale)
    metadata.tags = book.tags() or []

    return metadata


def parse_languages(langs, locale: str) -> List[str]:
    return [get_language_name(locale, get_lang3(lang)) for lang in langs]


def fetch_page(url):
    # Bytes, deliberately: the scraper decodes them itself, and handing lxml a
    # str selects libxml2's unicode path, where moly.hu pages can abort with a
    # fatal "internal error".
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; CalibreWeb/1.0)"},
        timeout=FETCH_TIMEOUT,
    )
    response.raise_for_status()
    return response.content


class Molyhu(Metadata):
    __name__ = 'Moly.hu'
    __id__ = moly_hu.MOLY_ID_KEY
    MOLY_ID_KEY = __id__
    MOLY_SOURCE_INFO = MetaSourceInfo(id=MOLY_ID_KEY, description=__name__, link=moly_hu.DOMAIN)

    def search(self, query: str, generic_cover: str = '', locale: str = 'en') -> Optional[List[MetaRecord]]:
        log.info(f'Search for: {query}')
        found_books = []
        if not self.active:
            return found_books

        title_tokens = list(self.get_title_tokens(query, strip_joiners=False))
        if not title_tokens:
            return found_books
        query = ' '.join(title_tokens)
        log.info(f'Query: {query}')

        try:
            book_ids = moly_hu.search(query, fetch_page)
        except Exception as err:
            # The other providers still answer; this one has nothing to add.
            log.warning(f'moly.hu search for "{query}" failed: {err}')
            return found_books
        log.info(f'Found book ids: {book_ids}')

        for moly_id in book_ids[:MAX_BOOKS]:
            try:
                book = moly_hu.book_for_id(moly_id, fetch_page)
            except Exception as err:
                # One page that will not load loses that hit alone.
                log.warning(f'Failed to fetch the page of {moly_id}: {err}')
                continue
            if not book:
                log.warning(f'No book found with id: {moly_id}')
                continue
            found_books.append(book_to_metadata(book, self.MOLY_SOURCE_INFO, locale))

        return found_books
