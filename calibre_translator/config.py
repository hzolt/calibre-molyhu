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


class ConfigWidget(QWidget):
    def __init__(self):
        QWidget.__init__(self)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(_('Custom column for the translator:')))
        self.column = QLineEdit(self)
        self.column.setText(prefs['translator_column'] or '')
        self.column.textChanged.connect(self.refresh_status)
        layout.addWidget(self.column)

        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()

        self.refresh_status()

    def current_column(self):
        try:
            from calibre.gui2.ui import get_gui

            gui = get_gui()
            if gui is None:
                return None
            metadata = gui.current_db.new_api.field_metadata.custom_field_metadata()
            return metadata.get((self.column.text() or '').strip())
        except Exception:
            return None

    def refresh_status(self):
        name = (self.column.text() or '').strip()
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
            _('%(name)s holds a %(kind)s. The translator is written to match it.')
            % {'name': name, 'kind': describe_column(column)})

    def save_settings(self):
        prefs['translator_column'] = (self.column.text() or '').strip()
