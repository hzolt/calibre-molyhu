from qt.core import QLabel, QLineEdit, QVBoxLayout, QWidget

from calibre_plugins.moly_hu_translator import prefs


def describe_column(column):
    """A short, human readable name for the column's shape."""
    datatype = column.get('datatype')
    if datatype != 'text':
        return datatype or _('unknown')
    if not column.get('is_multiple'):
        return _('single text value')
    if column.get('display', {}).get('is_names'):
        return _('multiple names, joined with "&"')
    return _('multiple comma separated values')


def custom_columns():
    """The library's custom columns, or an empty mapping outside the GUI."""
    try:
        from calibre.gui2.ui import get_gui

        gui = get_gui()
        if gui is None:
            return {}
        return gui.current_db.new_api.field_metadata.custom_field_metadata()
    except Exception:
        return {}


class ColumnRow:
    """One "which column does this field go into" setting.

    A label, the column name, and a line below it saying what that column
    turned out to be - the same three widgets for each of the three fields,
    so they are built once here rather than three times in the dialog.
    """

    def __init__(self, parent, layout, label, pref_key):
        self.pref_key = pref_key

        layout.addWidget(QLabel(label))
        self.column = QLineEdit(parent)
        self.column.setText(prefs[pref_key] or '')
        self.column.textChanged.connect(self.refresh_status)
        layout.addWidget(self.column)

        self.status = QLabel(parent)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.refresh_status()

    def name(self):
        return (self.column.text() or '').strip()

    def current_column(self):
        return custom_columns().get(self.name())

    def refresh_status(self):
        name = self.name()
        if not name:
            self.status.setText(_('No column set, so nothing will be written.'))
            return
        column = self.current_column()
        if column is None:
            self.status.setText(
                _('There is no %s column in this library.') % name)
            return
        # Any column type works: the value is shaped to fit whatever is here,
        # because calibre rejects a value that does not match the column.
        self.status.setText(
            _('%(name)s holds a %(kind)s. The value is written to match it.')
            % {'name': name, 'kind': describe_column(column)})

    def save(self):
        prefs[self.pref_key] = self.name()


class ConfigWidget(QWidget):
    def __init__(self):
        QWidget.__init__(self)
        layout = QVBoxLayout(self)

        self.rows = [
            ColumnRow(self, layout,
                      _('Custom column for the translator:'), 'translator_column'),
            ColumnRow(self, layout,
                      _('Custom column for the rating (0-100):'), 'rating_column'),
            ColumnRow(self, layout,
                      _('Custom column for the rating count:'), 'rating_count_column'),
            ColumnRow(self, layout,
                      _('Custom column for the statistics page URL:'),
                      'statistics_url_column'),
        ]
        layout.addStretch()

    def save_settings(self):
        for row in self.rows:
            row.save()
