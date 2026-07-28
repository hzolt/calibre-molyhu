from queue import Empty, Queue
import datetime
import re

from calibre.utils.date import utc_tz
from calibre.utils.cleantext import clean_ascii_chars
from calibre.ebooks.metadata.sources.base import Source, Option
from calibre.ebooks.metadata.book.base import Metadata
from calibre.ebooks.metadata import check_isbn

import calibre_plugins.moly_hu_reloaded.moly_hu as moly_hu

# Calibre's own rule for custom column lookup names: a '#', then a letter,
# then lower case letters, digits or underscores (see CreateNewCustomColumn).
LOOKUP_NAME_PATTERN = re.compile(r"^#[a-z][a-z0-9_]*$")


def is_valid_lookup_name(lookup_name):
    return bool(lookup_name) and bool(LOOKUP_NAME_PATTERN.match(lookup_name))


def default_translator_shape():
    """The column shape assumed when the library's own shape is not known."""
    return {
        'datatype': Molyhu.TRANSLATOR_DATATYPE,
        'is_multiple': dict(Molyhu.TRANSLATOR_IS_MULTIPLE_SEPARATORS),
        'display': dict(Molyhu.TRANSLATOR_DISPLAY),
    }


def translator_field_metadata(lookup_name, shape=None):
    """Build the custom column metadata the translator value is attached to.

    Calibre only applies a downloaded custom column value when the lookup
    name exists in the library *and* the datatype and is_multiple of the
    downloaded field match the library's column exactly
    (calibre/db/cache.py, set_metadata) - a mismatch drops the value without
    any error, which is why the shape is mirrored from the library instead of
    being fixed here. A column's datatype cannot be changed after it has been
    created, so assuming one shape would lock out every library whose column
    was made differently.

    'shape' carries the datatype, is_multiple and display the config widget
    read from the library. The remaining keys are the ones calibre's own
    FieldMetadata.add_custom_field() produces; table/column/colnum only
    describe where the value lives in the library, and calibre writes through
    its own field object, so those placeholders never reach the database.
    """
    shape = shape or default_translator_shape()
    return {
        'label': lookup_name[1:],
        'name': _('Translator'),
        'datatype': shape.get('datatype', Molyhu.TRANSLATOR_DATATYPE),
        'display': dict(shape.get('display') or {}),
        'is_multiple': dict(shape.get('is_multiple') or {}),
        'search_terms': [lookup_name],
        'table': 'custom_column_1',
        'column': 'value',
        'link_column': 'value',
        'category_sort': 'value',
        'colnum': 1,
        'kind': 'field',
        'is_custom': True,
        'is_category': True,
        'is_editable': True,
        'is_csp': False,
    }


def format_translator(translators, shape=None):
    """Shape the translator names to match the column they are written into.

    A multi-value column takes the list as it is. A single-value column - the
    plain "Text, column shown in the Tag browser" type - would reject a list,
    so the names are joined with the separator the column uses to display a
    list, falling back to a comma.
    """
    shape = shape or default_translator_shape()
    if shape.get('is_multiple'):
        return list(translators)
    separator = (shape.get('is_multiple') or {}).get('list_to_ui') or ', '
    return separator.join(translators)


def book_to_metadata(book, translator_column=None, translator_shape=None) -> Metadata:
    metadata = Metadata(book.title(), book.authors())
    # FIXME(crash): handle results' relevance from isbn/molyid?
    metadata.source_relevance = 0
    metadata.set_identifier(Molyhu.MOLY_ID_KEY, book.moly_id())
    metadata.set_identifier('isbn', check_isbn(book.isbn()))
    metadata.comments = book.description()
    metadata.tags = book.tags()
    metadata.languages = book.languages()
    metadata.publisher = book.publisher()
    if pubdate := book.publication_date():
        # Build a timezone-aware datetime: calibre converts naive pubdates
        # through the local timezone, which can shift the stored date by a day.
        metadata.pubdate = datetime.datetime(
            pubdate.year, pubdate.month, pubdate.day, tzinfo=utc_tz
        )
    metadata.rating = book.rating()
    if book.series():
        metadata.series = book.series()[0]
        metadata.series_index = book.series()[1]
    if translator_column and (translator := book.translator()):
        metadata.set_user_metadata(
            translator_column,
            translator_field_metadata(translator_column, translator_shape),
        )
        metadata.set(translator_column, format_translator(translator, translator_shape))
    return metadata


class Molyhu(Source):
    name = 'Moly.hu Reloaded'
    description = _('Downloads metadata and covers from moly.hu. Based on Hokutya Moly_hu plugin.')
    author = 'Imre NAGY'
    version = (0, 0, 0)
    minimum_calibre_version  = (5, 0, 0)

    MOLY_ID_KEY = 'moly_hu'

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
        'language',
        'languages'
    ])

    # The shape of the custom column the translator is written into. Calibre
    # drops the downloaded value without any error when the library's column
    # does not match this exactly, so the config widget checks it and warns.
    TRANSLATOR_DATATYPE = 'text'
    TRANSLATOR_IS_MULTIPLE = True
    TRANSLATOR_DISPLAY = {'is_names': True}
    TRANSLATOR_IS_MULTIPLE_SEPARATORS = {
        'cache_to_list': '|', 'ui_to_list': '&', 'list_to_ui': ' & '
    }

    # Not an Option: this is written by the config widget from the library's
    # own column metadata, not typed by hand, so it gets no generated editor.
    # identify() runs in a worker with no library handle and cannot look the
    # column up itself, hence the cache.
    KEY_TRANSLATOR_SHAPE = 'translator_column_shape'

    # Options
    KEY_MAX_BOOKS = 'max_books'
    KEY_TRANSLATOR_COLUMN = 'translator_column'
    options = (
        Option(KEY_MAX_BOOKS, 'number', 3, _('Maximum number of books to get'), _('The maximum number of books to process from the moly.hu search result')),
        Option(KEY_TRANSLATOR_COLUMN, 'string', '#translator', _('Custom column for the translator'),
               _('Lookup name of the custom column the moly.hu translator is written into, e.g. #translator. '
                 'Leave it empty to not download the translator at all. The column must be of type '
                 '"Text, column shown in the Tag browser" with "Contains names" ticked.')),
    )

    def config_widget(self):
        # Imported lazily: the config module pulls in Qt, which must not be
        # loaded by the headless worker process that runs identify().
        from calibre_plugins.moly_hu_reloaded.config import ConfigWidget

        return ConfigWidget(self)

    def translator_column_shape(self):
        """The shape of the translator column, as last seen in the library."""
        shape = self.prefs.get(self.KEY_TRANSLATOR_SHAPE)
        if isinstance(shape, dict) and shape.get('datatype'):
            return shape
        return default_translator_shape()

    def remember_translator_column_shape(self, column):
        """Cache the library's column shape for the worker to reuse.

        Called from the config widget, which is the only place that runs with
        a library at hand. Passing None forgets a previously cached shape, so
        a column that has gone away does not keep dictating the format.
        """
        if column is None:
            self.prefs[self.KEY_TRANSLATOR_SHAPE] = None
            return
        self.prefs[self.KEY_TRANSLATOR_SHAPE] = {
            'datatype': column.get('datatype'),
            'is_multiple': dict(column.get('is_multiple') or {}),
            'display': dict(column.get('display') or {}),
        }

    def identify(self, log, result_queue, abort, title, authors, identifiers, timeout):
        max_books = self.prefs[self.KEY_MAX_BOOKS]
        translator_column = (self.prefs[self.KEY_TRANSLATOR_COLUMN] or '').strip()
        if translator_column and not is_valid_lookup_name(translator_column):
            log.warning(
                f'Ignoring invalid translator column lookup name: {translator_column!r}'
            )
            translator_column = None
        translator_shape = self.translator_column_shape()
        if translator_column:
            log.info(
                f'Translator column: {translator_column} '
                f'(datatype {translator_shape["datatype"]}, '
                f'is_multiple {translator_shape["is_multiple"]})'
            )

        # Normalise the query with calibre's tokenizers, which drop leading
        # articles, punctuation and ZWJ noise that can throw off moly.hu's
        # search. The cleaned values are fed into the same term-builder so the
        # ISBN -> author+title -> title fallback order is preserved.
        clean_title = ' '.join(self.get_title_tokens(title)) if title else title
        clean_authors = (
            [' '.join(self.get_author_tokens(authors, only_first_author=True))]
            if authors
            else authors
        )
        search_terms = moly_hu.generate_search_terms(
            clean_title, clean_authors, identifiers
        )
        log.info(f'Search terms: {search_terms}')

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
            book_ids.extend(moly_hu.search(search_term, self._fetch_page))

        for index, id in enumerate(book_ids):
            if abort.is_set():
                log.info('Abort request received, returning.')
                return
            if index >= max_books:
                log.info(f'Max book limit reached, returning. (limit: {max_books})')
                return

            book = moly_hu.book_for_id(id, self._fetch_page)
            if not book:
                log.warning(f'No book found with id {id}')
                continue
            if covers := book.cover_urls():
                self.cache_identifier_to_cover_url(book.moly_id(), covers[0])
            self.cache_isbn_to_identifier(book.isbn(), book.moly_id())

            metadata = book_to_metadata(book, translator_column, translator_shape)
            # Only touches the standard fields, so the translator survives it.
            self.clean_downloaded_metadata(metadata)
            result_queue.put(metadata)

        error_message = None
        return error_message

    def _fetch_page(self, url):
        br = self.browser
        response = br.open(url)
        raw = response.read().strip()
        raw = raw.decode('utf-8', errors='replace')
        return clean_ascii_chars(raw)

    def get_book_url(self, identifiers):
        result = []
        moly_id = identifiers.get(self.MOLY_ID_KEY, None)
        if moly_id:
            result.append((self.MOLY_ID_KEY, moly_id, moly_hu.book_url_for_id(moly_id)))
        isbn = identifiers.get('isbn', None)
        if isbn:
            result.append(('isbn', isbn, f'http://www.mokka.hu/mokka/CCL/q=MEGA%3D{isbn}'))
        return tuple(result) or None

    def get_book_urls(self, identifiers):
        data = self.get_book_url(identifiers)
        if data is None:
            return ()
        return data

    def get_book_url_name(self, idtype, idval, url):
        if idtype == self.MOLY_ID_KEY:
            return 'moly.hu'
        if idtype == 'isbn':
            return 'mokka.hu'
        return None

    def get_cached_cover_url(self, identifiers):
        moly_id = identifiers.get(self.MOLY_ID_KEY, None)
        if not moly_id:
            isbn = identifiers.get('isbn', None)
            moly_id = self.cached_isbn_to_identifier(isbn)
        return self.cached_identifier_to_cover_url(moly_id)

    # original from: calibre/src/calibre/ebooks/metadata/sources/amazon.py
    def download_cover(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30, get_best_cover=False):
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
        except:
            log.exception('Failed to download cover from:', cached_url)
