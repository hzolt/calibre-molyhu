from calibre.customize import InterfaceActionBase
from calibre.utils.config import JSONConfig

# Calibre loads exactly one plugin class per zip (customize/zipplugin.py takes
# plugin_classes[0]), so this ships separately from the metadata source. It
# exists because a metadata source plugin cannot reliably fill a custom
# column: of calibre's three ways to apply a downloaded record, only
# db.set_metadata copies custom columns, and the plugin does not get to choose
# which one the GUI runs. An interface action runs in the GUI with the library
# at hand and writes the column directly, so none of that applies.

prefs = JSONConfig('plugins/moly_hu_translator')
prefs.defaults['translator_column'] = '#translator'
prefs.defaults['rating_column'] = '#moly_rating'
prefs.defaults['rating_count_column'] = '#moly_rating_count'


class MolyhuTranslator(InterfaceActionBase):
    name = 'Moly.hu Translator'
    description = ('Writes the moly.hu translator, rating and rating count into '
                   'custom columns for the selected books.')
    author = 'Imre NAGY'
    version = (0, 0, 0)
    minimum_calibre_version = (5, 0, 0)

    actual_plugin = 'calibre_plugins.moly_hu_translator.action:MolyhuTranslatorAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        # Imported here so that Qt is only pulled in when the dialog is opened.
        from calibre_plugins.moly_hu_translator.config import ConfigWidget

        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
