import os
import re
import time
import unicodedata
from functools import partial

from calibre import browser
from calibre.constants import config_dir
from calibre.gui2 import Dispatcher, error_dialog, info_dialog
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.threaded_jobs import ThreadedJob

from calibre_plugins.moly_hu_translator import prefs

import calibre_plugins.moly_hu_translator.moly_hu as moly_hu

MOLY_ID_KEY = 'moly_hu'


LOG_PATH = os.path.join(config_dir, 'plugins', 'moly_hu_translator.log')


def write_log_file(job):
    """Save the job log next to the plugin's settings, and return the path.

    Calibre keeps the same log in the Jobs list, but only until it is cleared,
    and only for whoever thinks to look there. A file survives the session and
    can be attached to a bug report. It holds one run: overwritten each time,
    so it cannot grow without bound.
    """
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, 'wb') as handle:
            handle.write(job.log.plain_text.encode('utf-8'))
        return LOG_PATH
    except Exception:
        # A log that cannot be written must not lose the results with it.
        import traceback

        traceback.print_exc()
        return None


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


def fold(text):
    """Strip a title down to what two spellings of the same book share.

    Accents are removed as well as case, so a title that lost its diacritics
    somewhere still compares equal.
    """
    stripped = unicodedata.normalize('NFKD', (text or '').replace('​', ''))
    return ''.join(c for c in stripped if not unicodedata.combining(c)).casefold()


def title_tokens(text):
    """The set of words in a title, ignoring case, accents and punctuation."""
    return {word for word in re.split(r'\W+', fold(text), flags=re.UNICODE) if word}


def is_match(book, info):
    """Is this moly.hu page really the book in the library?

    Nothing is written unless this says yes. A search returns a set of hits in
    no meaningful order - the whole back catalogue of the author, typically -
    so picking one without checking would file another book's translator.

    Titles are compared as sets of words rather than as strings, because a
    translated edition carries both the Hungarian and the original title and
    the two sides do not agree on the order or the separator: the library may
    hold "Mégis egymásnak teremtve? - So Not Meant To Be" where moly.hu has
    "So Not Meant To Be – Mégis egymásnak teremtve?". Requiring the sets to be
    equal keeps this strict - one title being merely contained in the other is
    not enough, or "Aliens" would match "A teljes Aliens-gyűjtemény 2."
    """
    isbn = (info.get('identifiers') or {}).get('isbn')
    if isbn and book.isbn() and only_digits(isbn) == only_digits(book.isbn()):
        return True
    page = title_tokens(book.title())
    return bool(page) and page == title_tokens(info.get('title'))


def find_book(info, log, abort=None):
    """Locate the book on moly.hu and return it, or None.

    Returns the parsed page rather than just the translator so the caller can
    log what was actually matched - which page a name came from is the first
    thing worth knowing when a result looks wrong.
    """
    moly_id = (info.get('identifiers') or {}).get(MOLY_ID_KEY)
    if moly_id:
        # A moly.hu id is already an identified match, so it is trusted.
        log('Hit URL: %s' % moly_hu.book_url_for_id(moly_id))
        return moly_hu.book_for_id(moly_id, fetch_page)

    terms = moly_hu.generate_search_terms(
        info.get('title'), info.get('authors'), info.get('identifiers') or {})
    log('Search terms: %s' % terms)

    seen = set()
    budget = CANDIDATE_BUDGET
    for term in terms:
        if budget <= 0 or (abort is not None and abort.is_set()):
            break
        log('Search for: %s' % term)
        for candidate in sorted(moly_hu.search(term, fetch_page)):
            if budget <= 0 or (abort is not None and abort.is_set()):
                break
            if candidate in seen:
                continue
            seen.add(candidate)
            budget -= 1
            book = moly_hu.book_for_id(candidate, fetch_page)
            if book and is_match(book, info):
                log('Hit URL: %s' % moly_hu.book_url_for_id(candidate))
                return book
    return None


def log_book(log, book, translators):
    """Report a match in the same shape as the metadata download log."""
    log('Found 1 results')
    for label, value in (
        ('Title', book.title()),
        ('Author(s)', ' & '.join(book.authors() or [])),
        ('Publisher', book.publisher()),
        ('Translator', ', '.join(translators or [])),
    ):
        log('%-20s: %s' % (label, value or ''))


def fetch_translators(books, abort=None, log=None, notifications=None):
    """Job body: look every book up on moly.hu. Runs off the GUI thread."""
    found, missing = {}, []
    total = max(len(books), 1)
    started = time.time()

    for index, (book_id, info) in enumerate(books.items()):
        if abort is not None and abort.is_set():
            log('Aborted after %d of %d books' % (index, total))
            break
        title = info.get('title') or ''
        if notifications is not None:
            notifications.put((index / total, title))

        log('\n' + '*' * 30 + ' %s ' % title + '*' * 30)
        book_started = time.time()
        try:
            book = find_book(info, log, abort)
        except Exception as err:
            log.error('Failed: %s' % err)
            missing.append(title)
            continue

        translators = book.translator() if book else None
        if translators:
            found[book_id] = translators
            log_book(log, book, translators)
        else:
            missing.append(title)
            log('Found 0 results' if book is None else 'No translator on the page')
        log('Downloading from moly.hu took %s' % (time.time() - book_started))

    log('\n' + '=' * 78)
    log('Fetched %d of %d books in %s seconds'
        % (len(found), total, time.time() - started))
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
        icon = self.load_icon()
        if icon is not None and not icon.isNull():
            self.qaction.setIcon(icon)
        self.qaction.triggered.connect(self.start)

    def load_icon(self):
        """Load the toolbar icon out of the plugin zip.

        get_icons is injected into the module namespace by calibre's plugin
        loader, so it does not exist when this file is imported outside a zip
        - running the tests, for one. Passing the plugin name lets an icon
        theme override the bundled image.
        """
        try:
            return get_icons(  # noqa: F821
                'images/moly_hu_translator.png', 'Moly.hu Translator')
        except NameError:
            return None

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

        # Dispatcher, not a plain callable: ThreadedJob invokes the callback
        # from the worker thread it ran the job on (start_work in
        # gui2/threaded_jobs.py calls self.callback(self) directly). Touching
        # the library view or opening a dialog from there freezes calibre.
        # Dispatcher is created here, on the GUI thread, and hands the call
        # back to it through a queued signal.
        job = ThreadedJob(
            'moly_hu_translator',
            _('Fetching translators from moly.hu for %d books') % len(books),
            fetch_translators, (books,), {},
            Dispatcher(partial(self.finished, column_name=column_name)),
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

        written, done_lines = {}, []
        for book_id, names in found.items():
            if not db.new_api.has_id(book_id):
                continue
            written[book_id] = format_for_column(names, column)
            done_lines.append('%s: %s' % (
                db.new_api.field_for('title', book_id), ', '.join(names)))

        if written:
            db.new_api.set_field(column_name, written)
            self.gui.library_view.model().refresh_ids(list(written), current_row=-1)
            self.gui.tags_view.recount()

        # The summary stays to one line and the per book detail goes to
        # det_msg. info_dialog lays the message out in a word wrapped label
        # that grows with its content, so a long list of books pushes the
        # dialog past the edge of the calibre window. det_msg is shown in the
        # collapsible "Show details" pane instead, which scrolls.
        summary = _('Wrote the translator for %(done)d of %(total)d books.') % {
            'done': len(written), 'total': len(written) + len(missing)}

        sections = []
        if done_lines:
            sections.append(_('Written:') + '\n' + '\n'.join(sorted(done_lines)))
        if missing:
            sections.append(
                _('No translator found:') + '\n' + '\n'.join(sorted(missing)))

        log_path = write_log_file(job)
        if log_path:
            summary += '\n' + _('Log: %s') % log_path

        info_dialog(self.gui, _('Translators fetched'), summary,
                    det_msg='\n\n'.join(sections), show=True, show_copy_button=True)
