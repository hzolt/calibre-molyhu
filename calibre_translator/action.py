import os
import re
import time

from calibre import browser
from calibre.constants import config_dir
from calibre.gui2 import Dispatcher, error_dialog, info_dialog
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.threaded_jobs import ThreadedJob

from calibre_plugins.moly_hu_translator import EBOOK_MARKER, prefs

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


# What the action reads off a moly.hu page and writes into the library: the
# key of the value in a result record, the preference holding the name of the
# column it goes into, and the label it is reported under in the log and the
# summary. Everything that has to happen once per field is driven by this.
FIELDS = (
    ('translator', 'translator_column', _('Translator')),
    ('rating', 'rating_column', _('Rating')),
    ('rating_count', 'rating_count_column', _('Rating count')),
    ('statistics_url', 'statistics_url_column', _('Statistics URL')),
    ('type', 'type_column', _('Type')),
)


def ebook_marker():
    """The mark written for an ebook, or None when it has been cleared.

    Emptying the setting is a way of turning the mark off that does not
    require unsetting the column as well.
    """
    marker = prefs['ebook_marker']
    if marker is None:
        marker = EBOOK_MARKER
    return marker.strip() or None


def read_fields(book):
    """Everything the action writes, read off one moly.hu page.

    The rating is the percentage moly.hu displays rather than Book.rating(),
    which rounds it onto calibre's 0-5 scale and so cannot tell 90% from 94%.

    The statistics URL costs no extra page open: the book page already links
    to it, and where it does not the address follows from the book's id.

    The type marks the books whose data was read off an ebook edition, which
    is the edition moly.hu is read from wherever the page has one. A page with
    printed editions only leaves the field empty rather than marking the book
    as something it may not be: calibre knows what formats the library holds,
    moly.hu only knows what was published.
    """
    return {
        'translator': book.translator(),
        'rating': book.rating_percent(),
        'rating_count': book.rating_count(),
        'statistics_url': book.statistics_url(),
        'type': ebook_marker() if book.is_ebook() else None,
    }


def describe_value(value):
    """A value as it reads in the log and in the summary."""
    if value is None:
        return ''
    if isinstance(value, list):
        return ', '.join(value)
    if isinstance(value, float) and value.is_integer():
        # The percentages are whole numbers; "94" beats "94.0" in a report.
        return str(int(value))
    return str(value)


def format_for_column(value, column):
    """Shape a value to match the column it is written into.

    Calibre refuses a value whose shape does not match the column, and a
    column's type cannot be changed once created, so this follows the library
    rather than the other way round.
    """
    if isinstance(value, list):
        return format_names_for_column(value, column)
    if isinstance(value, str):
        return format_text_for_column(value, column)
    return format_number_for_column(value, column)


def format_names_for_column(names, column):
    """A multi-value column takes the list as it is; a single-value one would
    reject it, so the names are joined with the separator the column uses to
    display a list.
    """
    is_multiple = column.get('is_multiple') or {}
    if is_multiple:
        return list(names)
    return (is_multiple.get('list_to_ui') or ', ').join(names)


def format_text_for_column(text, column):
    """Text goes in as it stands, except into a multi-value column, which
    takes a list and would otherwise split the text on its separator.
    """
    if column.get('is_multiple'):
        return [text]
    return text


def format_number_for_column(value, column):
    """Numbers carry a type, so the column's own type decides the shape."""
    datatype = column.get('datatype')
    if datatype == 'float':
        return float(value)
    if datatype == 'int':
        return int(round(value))
    if datatype == 'rating':
        # A calibre rating is 0-10 half stars, so a percentage has to be
        # rescaled rather than handed over as it stands.
        return max(0, min(10, int(round(value / 10.0))))
    if column.get('is_multiple'):
        return [describe_value(value)]
    return describe_value(value)


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


def is_match(book, info):
    """Is this moly.hu page really the book in the library?

    Nothing is written unless this says yes. A search returns a set of hits in
    no meaningful order - the whole back catalogue of the author, typically -
    so picking one without checking would file another book's translator.

    An ISBN settles it on its own. Failing that the titles have to agree, in
    one of the two ways ``moly_hu.title_match_kind`` tells apart, and where
    they agree on no more than a part of the title the authors have to bear it
    out: a search for a bare title is answered with every book whose title
    carries the word, and the part a translated book shares with the library
    can be a common enough word on its own - "Kicsúszás" is.
    """
    isbn = (info.get('identifiers') or {}).get('isbn')
    # Every edition of the page is compared, not just the one the data is read
    # from: the page's values come off the ebook edition where there is one,
    # while the library may hold the paperback, and the two ISBNs differ
    # although both name this book.
    if isbn:
        wanted = only_digits(isbn)
        if any(wanted == only_digits(candidate)
               for candidate in (book.isbns() or [])):
            return True
    kind = moly_hu.title_match_kind(book.title(), info.get('title'))
    if kind is None:
        return False
    if kind == 'fragment':
        return moly_hu.authors_overlap(book.authors(), info.get('authors'))
    return True


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
        log('Search URL: %s' % moly_hu.search_url(term))
        hits = sorted(moly_hu.search(term, fetch_page))
        log('%d search hit(s): %s' % (len(hits), ', '.join(hits) or '-'))
        for candidate in hits:
            if abort is not None and abort.is_set():
                break
            if budget <= 0:
                # The budget is spent across all the terms together, not per
                # term, so it can run out with hits still on the list.
                log('Candidate budget of %d spent, the rest of the hits go '
                    'unopened' % CANDIDATE_BUDGET)
                break
            if candidate in seen:
                continue
            seen.add(candidate)
            budget -= 1
            book = moly_hu.book_for_id(candidate, fetch_page)
            if book and is_match(book, info):
                log('Hit URL: %s' % moly_hu.book_url_for_id(candidate))
                return book
            if book is None:
                log('No page for %s' % candidate)
            else:
                log('Not this book: %s is "%s" by %s'
                    % (candidate,
                       book.title() or '',
                       ' & '.join(book.authors() or []) or '?'))
    # Which of the two ways the search came to nothing is the first thing worth
    # knowing, and "Found 0 results" on its own does not say.
    if not seen:
        log('No search hit for any of the terms')
    else:
        log('None of the %d page(s) opened is "%s"'
            % (len(seen), info.get('title') or ''))
    return None


def log_book(log, book, values):
    """Report a match in the same shape as the metadata download log."""
    log('Found 1 results')
    rows = [
        ('Title', book.title()),
        ('Author(s)', ' & '.join(book.authors() or [])),
        ('Publisher', book.publisher()),
    ]
    rows.extend((label, describe_value(values.get(key)))
                for key, pref_key, label in FIELDS)
    for label, value in rows:
        log('%-20s: %s' % (label, value or ''))


def fetch_book_data(books, abort=None, log=None, notifications=None):
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

        # Each field stands on its own: a page with a rating but no translator
        # is still worth writing, so anything the page does carry is kept.
        values = {key: value
                  for key, value in (read_fields(book) if book else {}).items()
                  if value is not None}
        if values:
            found[book_id] = values
            log_book(log, book, values)
        else:
            missing.append(title)
            log('Found 0 results' if book is None else 'Nothing to write from the page')
        log('Downloading from moly.hu took %s' % (time.time() - book_started))

    log('\n' + '=' * 78)
    log('Fetched %d of %d books in %s seconds'
        % (len(found), total, time.time() - started))
    return found, missing


class MolyhuTranslatorAction(InterfaceAction):
    name = 'Moly.hu Translator'
    action_spec = (
        _('Fetch data from moly.hu'),
        None,
        _('Write the moly.hu translator, rating, rating count, statistics '
          'page URL and ebook marker of the selected books into custom '
          'columns'),
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

    def resolve_columns(self, db):
        """The configured columns that exist in this library, keyed by field.

        A field whose column is unset or absent is simply not written, so one
        missing column does not cost the run the others.
        """
        metadata = db.new_api.field_metadata.custom_field_metadata()
        columns = {}
        for key, pref_key, label in FIELDS:
            name = (prefs[pref_key] or '').strip()
            if not name:
                continue
            column = metadata.get(name)
            if column is not None:
                columns[key] = (name, column)
        return columns

    def start(self):
        db = self.gui.current_db
        if not self.resolve_columns(db):
            return error_dialog(
                self.gui, _('No columns configured'),
                _('Set at least one custom column to write into in the plugin '
                  'configuration first, and make sure it exists in this '
                  'library.'), show=True)

        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            return error_dialog(
                self.gui, _('No books selected'),
                _('Select the books to fetch the data for.'), show=True)

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
            _('Fetching data from moly.hu for %d books') % len(books),
            fetch_book_data, (books,), {},
            Dispatcher(self.finished),
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(_('Fetching data from moly.hu'), 3000)

    def finished(self, job):
        if job.failed:
            return self.gui.job_exception(job, dialog_title=_('Failed to fetch data'))

        found, missing = job.result
        db = self.gui.current_db
        # Re-read the columns: the job ran while the GUI stayed live, so the
        # library could have changed underneath it.
        columns = self.resolve_columns(db)
        if not columns:
            return error_dialog(
                self.gui, _('No columns configured'),
                _('None of the configured columns exist in this library any more.'),
                show=True)

        # One set_field per column rather than per book: it is a single bulk
        # write, and the fields do not necessarily cover the same books.
        writes, done_lines = {}, []
        for book_id, values in found.items():
            if not db.new_api.has_id(book_id):
                continue
            reported = []
            for key, pref_key, label in FIELDS:
                target, value = columns.get(key), values.get(key)
                if target is None or value is None:
                    continue
                name, column = target
                writes.setdefault(name, {})[book_id] = format_for_column(value, column)
                reported.append('%s: %s' % (label, describe_value(value)))
            if reported:
                done_lines.append('%s - %s' % (
                    db.new_api.field_for('title', book_id), ', '.join(reported)))

        touched = set()
        for name, values_by_id in writes.items():
            db.new_api.set_field(name, values_by_id)
            touched.update(values_by_id)
        if touched:
            self.gui.library_view.model().refresh_ids(list(touched), current_row=-1)
            self.gui.tags_view.recount()

        # The summary stays to one line and the per book detail goes to
        # det_msg. info_dialog lays the message out in a word wrapped label
        # that grows with its content, so a long list of books pushes the
        # dialog past the edge of the calibre window. det_msg is shown in the
        # collapsible "Show details" pane instead, which scrolls.
        summary = _('Wrote data for %(done)d of %(total)d books.') % {
            'done': len(done_lines), 'total': len(found) + len(missing)}

        sections = []
        if done_lines:
            sections.append(_('Written:') + '\n' + '\n'.join(sorted(done_lines)))
        if missing:
            sections.append(
                _('No data found:') + '\n' + '\n'.join(sorted(missing)))

        log_path = write_log_file(job)
        if log_path:
            summary += '\n' + _('Log: %s') % log_path

        info_dialog(self.gui, _('Data fetched'), summary,
                    det_msg='\n\n'.join(sections), show=True, show_copy_button=True)
