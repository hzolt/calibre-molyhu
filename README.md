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
| **Moly.hu Translator** | `scripts/create_calibre_translator_plugin_zip.sh` | calibre toolbar button that writes the translator, rating, rating count and statistics page URL into custom columns |
| **calibre-web provider** | `scripts/create_calibreweb_plugin_zip.sh` | the same metadata for calibre-web |

The two calibre plugins are separate because calibre loads exactly one plugin
class per zip (`plugin_classes[0]` in `calibre/customize/zipplugin.py`), and
because they need different things from calibre: a metadata source runs in a
worker with no library handle, while writing a custom column needs the
library. Install both if you want the translator.

### Moly.hu Translator

Adds a **Fetch data from moly.hu** toolbar button. Select books, press it, and
four values off the moly.hu book page are written into custom columns with
`db.new_api.set_field`:

| Field | Default column | What it holds |
|---|---|---|
| Translator | `#translator` | the names behind the edition's "Fordította" label |
| Rating | `#moly_rating` | the score as moly.hu shows it, a percentage from 0 to 100 (`94%` → `94`) |
| Rating count | `#moly_rating_count` | how many people rated it, from the "62 csillagozás" link |
| Statistics URL | `#moly_stats_raw` | the book's `/statisztika` page, e.g. `https://moly.hu/konyvek/dennis-e-taylor-mi-bob/statisztika` |

The rating is kept as the percentage rather than as calibre's 0-5 stars, which
cannot tell 90% from 94%. The metadata source plugin still fills calibre's own
rating field with the rounded 0-5 value; these columns are separate from it.

The statistics URL costs no extra page open: the book page links to it from
the "csillagozás" anchor, and a book too new to have that anchor still has the
page, whose address follows from the book's id. In a short text column calibre
renders it as a clickable link in *Book details*.

Set the columns in *Preferences → Plugins → Moly.hu Translator*. Any column
type works: the value is shaped to fit whatever is there, because calibre
rejects a value whose datatype does not match the column, and a column's type
cannot be changed once it has been created. Leaving a column blank, or naming
one that does not exist in the library, simply skips that field; the run only
refuses to start when none of them resolve.

Each field is written on its own, so a book whose page carries a rating but no
translator still gets its rating.

A book is only written when the moly.hu page is confirmed to be the right one,
by a matching ISBN or a matching title. `search()` returns an unordered set of
hits - a title search answers with the author's whole back catalogue - so
taking one on trust would file another book's data. Books that cannot be
confirmed are reported as not found instead.

Each run writes a log in the style of the metadata download log - the page it
matched, the search terms it tried, and the title, author, publisher,
translator, rating and rating count it read - to `moly_hu_translator.log` in
the calibre configuration directory, whose path is shown when the run
finishes. The same log is in calibre's Jobs list until it is cleared; the file
outlives the session. It holds one run and is overwritten each time.

The data deliberately does **not** come from the metadata source plugin.
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
