# Moly.hu Metadata source

Based on Hokutya's [moly.hu calibre plugin](https://www.mobileread.com/forums/showthread.php?t=193302) from mobileread.com.

Metadata from https://moly.hu

Supported applications:
- [calibre](https://calibre-ebook.com/)
- [calibre-web](https://github.com/janeczku/calibre-web)

## Usage

Search for book in command-line: `python -m moly_hu.main "raymond feist"`

This repository builds three artifacts from one shared scraper
(`moly_hu/src/moly_hu/moly_hu.py`), which is pure lxml and imports nothing
from calibre. Each front end copies it into its own package at build time:

| Artifact | Built by | What it does |
|---|---|---|
| **Moly.hu Reloaded** | `scripts/create_calibre_plugin_zip.sh` | calibre metadata source: title, authors, series, publisher, publication date, ISBN, tags, rating, comments, covers |
| **Moly.hu Translator** | `scripts/create_calibre_translator_plugin_zip.sh` | calibre toolbar button that writes the translator into a custom column |
| **calibre-web provider** | `scripts/create_calibreweb_plugin_zip.sh` | the same metadata for calibre-web |

The two calibre plugins are separate because calibre loads exactly one plugin
class per zip (`plugin_classes[0]` in `calibre/customize/zipplugin.py`), and
because they need different things from calibre: a metadata source runs in a
worker with no library handle, while writing a custom column needs the
library. Install both if you want the translator.

### Moly.hu Translator

Adds a **Fetch translator from moly.hu** toolbar button. Select books, press
it, and the translator is written into a custom column with
`db.new_api.set_field`.

Set the column in *Preferences → Plugins → Moly.hu Translator*. Any column
type works: the value is shaped to fit whatever is there, because calibre
rejects a value whose datatype does not match the column, and a column's type
cannot be changed once it has been created.

A book is only written when the moly.hu page is confirmed to be the right one,
by a matching ISBN or a matching title. `search()` returns an unordered set of
hits - a title search answers with the author's whole back catalogue - so
taking one on trust would file another book's translator. Books that cannot be
confirmed are reported as not found instead.

Each run writes a log in the style of the metadata download log - the page it
matched, the search terms it tried, and the title, author, publisher and
translator it read - to `moly_hu_translator.log` in the calibre configuration
directory, whose path is shown when the run finishes. The same log is in
calibre's Jobs list until it is cleared; the file outlives the session. It
holds one run and is overwritten each time.

The translator deliberately does **not** come from the metadata source plugin.
Calibre applies a downloaded record through one of three paths, and only
`db.set_metadata` copies custom columns: `update_from_mi` (the Edit metadata
dialog) and `CompareMany` (the review dialog) handle standard fields only, and
a plugin does not get to choose which one the GUI runs. The ISBN merge
discards custom columns as well. A toolbar action has none of those problems.

## Contributing
```
python -m venv .venv
source .venv/bin/activate
pip install -e moly_hu[dev]

python -m pytest -v moly_hu/tests/
```

Reload in calibre: `calibre-debug -s; calibre-customize -b .; calibre`

VSCode code completion (calibre and calibre-web is one level up in directory tree):
```
{
    "python.autoComplete.extraPaths": [
        "../calibre/src",
        "../calibre-web"
    ],
    "python.analysis.extraPaths": [
        "../calibre/src",
        "../calibre-web"
    ],
}
```
