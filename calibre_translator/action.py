import re

from calibre import browser
from calibre.gui2 import error_dialog, info_dialog
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.threaded_jobs import ThreadedJob

from calibre_plugins.moly_hu_translator import prefs

import calibre_plugins.moly_hu_translator.moly_hu as moly_hu

MOLY_ID_KEY = 'moly_hu'


def format_for_column(translators, column):
    """Shape the names to match the column they are written into.

    A multi-value column takes the list as it is; a single-value one would
    reject it, so the names are joined with the separator the column uses to
    display a list. Calibre refuses a value whose shape does not match the
    column, so this has to follow the library rather than the other way round.
    """
    is_multiple = column.get('is_multiple') or {}
    if is_multiple:
        return list(translators)
    return (is_multiple.get('list_to_ui') or ', ').join(translators)


def fetch_page(url):
    # Bytes, deliberately: handing lxml a str selects libxml2's unicode path,
    # where moly.hu pages can abort with a fatal "internal error".
    return browser().open(url).read()


# How many search hits are opened before giving up on a book. moly.hu answers
# a title search with everything by the author, so the first hit is routinely
# the wrong book.
CANDIDATE_BUDGET = 6


def only_digits(text):
    return re.sub(r'\D', '', text or '')


def normalise(text):
    """Fold a title down to what two spellings of the same book share."""
    return re.sub(r'\W+', '', (text or '').replace('​', ''), flags=re.UNICODE).casefold()


def is_match(book, info):
    """Is this moly.hu page really the book in the library?

    Nothing is written unless this says yes. A search returns a set of hits in
    no meaningful order - the whole back catalogue of the author, typically -
    so picking one without checking would file another book's translator.
    """
    isbn = (info.get('identifiers') or {}).get('isbn')
    if isbn and book.isbn() and only_digits(isbn) == only_digits(book.isbn()):
        return True
    return bool(book.title()) and normalise(book.title()) == normalise(info.get('title'))


def find_translator(info, log, abort=None):
    """Locate the book on moly.hu and return its translator names, or None."""
    moly_id = (info.get('identifiers') or {}).get(MOLY_ID_KEY)
    if moly_id:
        # A moly.hu id is already an identified match, so it is trusted.
        log('  reading', moly_hu.book_url_for_id(moly_id))
        book = moly_hu.book_for_id(moly_id, fetch_page)
        return book.translator() if book else None

    seen = set()
    budget = CANDIDATE_BUDGET
    for term in moly_hu.generate_search_terms(
        info.get('title'), info.get('authors'), info.get('identifiers') or {}
    ):
        if budget <= 0 or (abort is not None and abort.is_set()):
            break
        log('  searching for', term)
        for candidate in sorted(moly_hu.search(term, fetch_page)):
            if budget <= 0 or (abort is not None and abort.is_set()):
                break
            if candidate in seen:
                continue
            seen.add(candidate)
            budget -= 1
            book = moly_hu.book_for_id(candidate, fetch_page)
            if book and is_match(book, info):
                log('  matched', candidate)
                return book.translator()
    return None


def fetch_translators(books, abort=None, log=None, notifications=None):
    """Job body: look every book up on moly.hu. Runs off the GUI thread."""
    found, missing = {}, []
    total = max(len(books), 1)
    for index, (book_id, info) in enumerate(books.items()):
        if abort is not None and abort.is_set():
            break
        title = info.get('title') or ''
        if notifications is not None:
            notifications.put((index / total, title))
        log('%s:' % title)
        try:
            translators = find_translator(info, log, abort)
        except Exception as err:
            log.error('  failed:', err)
            missing.append(title)
            continue
        if translators:
            found[book_id] = translators
            log('  translator:', ', '.join(translators))
        else:
            missing.append(title)
            log('  no translator found')
    return found, missing


class MolyhuTranslatorAction(InterfaceAction):
    name = 'Moly.hu Translator'
    action_spec = (
        _('Fetch translator from moly.hu'),
        None,
        _('Write the moly.hu translator of the selected books into a custom column'),
        None,
    )
    action_type = 'current'

    def genesis(self):
        self.qaction.triggered.connect(self.start)

    def start(self):
        column_name = (prefs['translator_column'] or '').strip()
        if not column_name:
            return error_dialog(
                self.gui, _('No column configured'),
                _('Set the custom column to write the translator into in the '
                  'plugin configuration first.'), show=True)

        db = self.gui.current_db
        column = db.new_api.field_metadata.custom_field_metadata().get(column_name)
        if column is None:
            return error_dialog(
                self.gui, _('Column not found'),
                _('There is no %s column in this library.') % column_name, show=True)

        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            return error_dialog(
                self.gui, _('No books selected'),
                _('Select the books to fetch the translator for.'), show=True)

        model = self.gui.library_view.model()
        books = {}
        for row in rows:
            book_id = model.id(row)
            mi = db.new_api.get_metadata(book_id)
            books[book_id] = {
                'title': mi.title,
                'authors': list(mi.authors or []),
                'identifiers': dict(mi.identifiers or {}),
            }

        job = ThreadedJob(
            'moly_hu_translator',
            _('Fetching translators from moly.hu for %d books') % len(books),
            fetch_translators, (books,), {},
            lambda job: self.finished(job, column_name),
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(_('Fetching translators from moly.hu'), 3000)

    def finished(self, job, column_name):
        if job.failed:
            return self.gui.job_exception(job, dialog_title=_('Failed to fetch translators'))

        found, missing = job.result
        db = self.gui.current_db
        # Re-read the column: the job ran while the GUI stayed live, so the
        # library could have changed underneath it.
        column = db.new_api.field_metadata.custom_field_metadata().get(column_name)
        if column is None:
            return error_dialog(
                self.gui, _('Column not found'),
                _('There is no %s column in this library.') % column_name, show=True)

        written = {
            book_id: format_for_column(names, column)
            for book_id, names in found.items()
            if db.new_api.has_id(book_id)
        }
        if written:
            db.new_api.set_field(column_name, written)
            self.gui.library_view.model().refresh_ids(list(written), current_row=-1)
            self.gui.tags_view.recount()

        message = _('Wrote the translator for %(done)d of %(total)d books.') % {
            'done': len(written), 'total': len(written) + len(missing)}
        if missing:
            message += '\n\n' + _('No translator found for:') + '\n' + '\n'.join(missing)
        info_dialog(self.gui, _('Translators fetched'), message,
                    show=True, show_copy_button=bool(missing))
