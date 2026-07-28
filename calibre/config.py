from qt.core import QLabel, QPushButton, Qt

from calibre.gui2.metadata.config import ConfigWidget as DefaultConfigWidget

from calibre_plugins.moly_hu_reloaded import Molyhu, is_valid_lookup_name


def _current_db():
    """Return the library of the running calibre GUI, or None.

    The plugin normally runs headless, where there is no GUI and no library
    to look at. Only the config widget is guaranteed to run inside the GUI
    process, and even there the lookup is defensive so a missing or changed
    calibre internal degrades into "cannot check" instead of breaking the
    preferences dialog.
    """
    try:
        from calibre.gui2.ui import get_gui

        gui = get_gui()
        return gui.current_db if gui is not None else None
    except Exception:
        return None


def _column_metadata(lookup_name):
    db = _current_db()
    if db is None:
        return None
    try:
        return db.new_api.field_metadata.custom_field_metadata().get(lookup_name)
    except Exception:
        return None


def _matches_expected_shape(column):
    return (
        column.get('datatype') == Molyhu.TRANSLATOR_DATATYPE
        and column.get('is_multiple') == Molyhu.TRANSLATOR_IS_MULTIPLE_SEPARATORS
    )


class ConfigWidget(DefaultConfigWidget):
    """The stock metadata source config, plus a translator column helper.

    The stock widget already renders an editor for every entry in
    Molyhu.options, so the lookup name itself needs no extra UI. What it
    cannot do is tell the user whether that column actually exists and has
    the right type, which matters because calibre discards a downloaded
    custom column value silently when the types differ.
    """

    def __init__(self, plugin):
        DefaultConfigWidget.__init__(self, plugin)

        self.translator_status = QLabel(self)
        self.translator_status.setWordWrap(True)
        self.translator_status.setTextFormat(Qt.TextFormat.RichText)
        self.overl.addWidget(self.translator_status)

        self.create_column_button = QPushButton(_('Create the translator column'), self)
        self.create_column_button.clicked.connect(self.create_translator_column)
        self.overl.addWidget(self.create_column_button)

        column_widget = self.get_option_widget(Molyhu.KEY_TRANSLATOR_COLUMN)
        if column_widget is not None:
            column_widget.textChanged.connect(self.refresh_translator_status)

        self.refresh_translator_status()

    def translator_column_name(self):
        widget = self.get_option_widget(Molyhu.KEY_TRANSLATOR_COLUMN)
        if widget is None:
            return (self.plugin.prefs[Molyhu.KEY_TRANSLATOR_COLUMN] or '').strip()
        return (widget.text() or '').strip()

    def get_option_widget(self, name):
        # The stock widget keeps the generated editors in self.widgets, each
        # tagged with the Option it was built from.
        for widget in getattr(self, 'widgets', []):
            if getattr(widget, 'opt', None) is not None and widget.opt.name == name:
                return widget
        return None

    def refresh_translator_status(self):
        lookup_name = self.translator_column_name()
        self.create_column_button.setEnabled(False)

        if not lookup_name:
            self.translator_status.setText(
                _('The translator is not downloaded while the column name is empty.')
            )
            return

        if not is_valid_lookup_name(lookup_name):
            self.translator_status.setText(
                _('<b>%s is not a valid lookup name.</b> It must start with "#", '
                  'then a letter, then only lower case letters, digits or '
                  'underscores.') % lookup_name
            )
            return

        if _current_db() is None:
            self.translator_status.setText(
                _('No library is open, so the %s column cannot be checked.')
                % lookup_name
            )
            return

        column = _column_metadata(lookup_name)
        if column is None:
            self.translator_status.setText(
                _('The %s column does not exist in this library yet.') % lookup_name
            )
            self.create_column_button.setEnabled(True)
            return

        if _matches_expected_shape(column):
            self.translator_status.setText(
                _('The %s column is ready to receive the translator.') % lookup_name
            )
            return

        self.translator_status.setText(
            _('<b>The %(name)s column exists, but its type is "%(actual)s".</b> '
              'The translator is only stored in a column of type "Text, column '
              'shown in the Tag browser" with "Contains names" ticked. Calibre '
              'discards the downloaded value without any warning until the '
              'column is changed, or another column name is used here.')
            % {'name': lookup_name, 'actual': column.get('datatype')}
        )

    def create_translator_column(self):
        from calibre.gui2 import error_dialog, info_dialog
        from calibre.gui2.preferences.create_custom_column import CreateNewCustomColumn
        from calibre.gui2.ui import get_gui

        lookup_name = self.translator_column_name()
        creator = CreateNewCustomColumn(get_gui())
        if creator.must_restart():
            return error_dialog(
                self, _('Restart needed'),
                _('Calibre must be restarted before a new column can be added.'),
                show=True,
            )

        result, message = creator.create_column(
            lookup_name,
            _('Translator'),
            Molyhu.TRANSLATOR_DATATYPE,
            Molyhu.TRANSLATOR_IS_MULTIPLE,
            display=dict(Molyhu.TRANSLATOR_DISPLAY),
        )

        if result == CreateNewCustomColumn.Result.CANCELED:
            return
        if result != CreateNewCustomColumn.Result.COLUMN_ADDED:
            return error_dialog(
                self, _('Could not create the column'), message, show=True
            )

        info_dialog(
            self, _('Column created'),
            _('The %s column was created. Restart calibre for it to appear.')
            % message,
            show=True,
        )
        self.refresh_translator_status()
