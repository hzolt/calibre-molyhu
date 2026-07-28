# Moly.hu Metadata source

Based on Hokutya's [moly.hu calibre plugin](https://www.mobileread.com/forums/showthread.php?t=193302) from mobileread.com.

Metadata from https://moly.hu

Supported applications:
- [calibre](https://calibre-ebook.com/)
- [calibre-web](https://github.com/janeczku/calibre-web)

## Usage

Search for book in command-line: `python -m moly_hu.main "raymond feist"`

### Translator: use the Moly.hu Translator plugin (calibre only)

`scripts/create_calibre_translator_plugin_zip.sh` builds a second, separate
plugin - calibre loads one plugin class per zip - that adds a **Fetch
translator from moly.hu** toolbar button. Select books, press it, and it
writes the translator straight into a custom column with
`db.new_api.set_field`.

This is the recommended way to fill a translator column, because it runs in
the GUI with the library at hand and so avoids every limitation listed below:
it does not go through calibre's merge, it reads the column's real type
instead of caching it, and it does not depend on which apply dialog is used.
Set the column in *Preferences → Plugins → Moly.hu Translator*; any column
type works, and the value is shaped to fit it.

A book is only written when the moly.hu page is confirmed to be the right one
- by a matching ISBN, or a matching title. moly.hu answers a title search with
the author's whole back catalogue in no particular order, so an unverified hit
would file another book's translator. Books that cannot be confirmed are
reported as not found rather than guessed at.

### Translator custom column via the metadata source (has caveats)

moly.hu credits the translator on the edition line, and the calibre plugin can
write it into a custom column. Set the lookup name in *Preferences → Metadata
download → Moly.hu Reloaded* (`#translator` by default, empty disables it).

**Open that config page once after pointing it at a column.** Calibre applies a
downloaded custom column value only when the datatype matches the library's
column exactly, and a column's type cannot be changed after it is created. The
plugin therefore mirrors whatever shape your column has: a single-value text
column receives the names joined together, a multi-value one receives them as
separate values. Reading that shape needs the library, which the metadata
download worker does not have, so the config page reads it and remembers it.
Until it has been opened once, the plugin assumes a names-like column.

The config page states which shape it found and shows how two translators would
be stored. If the column does not exist yet, a button there creates one
(calibre has to be restarted afterwards, as for any new column).

All edition-derived fields (publisher, ISBN, publication date, translator) are
read from the **first** edition listed on the page, so they always describe the
same edition.

#### Download from the book list, not from the Edit metadata dialog

**The Download metadata button inside the Edit metadata dialog cannot fill a
custom column.** That dialog copies a downloaded record with `update_from_mi`
(`calibre/gui2/metadata/single.py`), which only knows the standard fields:
title, authors, rating, publisher, tags, identifiers, pubdate, series,
languages and comments. The custom column widgets keep the values they were
opened with, and saving the dialog commits those, so the translator is
discarded before calibre gets anywhere near writing it. No metadata source
plugin can change this.

Select the book in the library view instead and use **Edit metadata →
Download metadata and covers** (Ctrl+D). That path applies the record with
`db.set_metadata`, which does write custom columns. It works with a single
book selected.

**Let it apply directly - do not use "Review downloaded metadata"** on the
popup that appears when the download finishes. The review dialog
(`CompareMany` in `calibre/gui2/metadata/diff.py`) builds its editors from a
list of standard fields and has no custom column support at all, so choosing
it discards the translator just as the Edit metadata dialog does.

Only the plain apply reaches `db.set_metadata`, which is the one place in
calibre that copies custom columns out of a downloaded record.

#### Turn off the sources that compete for the same book

**The translator only survives when no other enabled metadata source returns the
same book.** This is a calibre limitation, not something the plugin can work
around: when several sources return a result with the same ISBN, or the same
title and authors, calibre merges them into one record that it rebuilds from
the standard fields alone (`ISBNMerge.merge` in
`calibre/ebooks/metadata/sources/identify.py`). Custom columns are dropped
there, and metadata source plugins get no hook to prevent it.

In practice a Hungarian edition is also carried by Goodreads and StoryGraph via
its ISBN, so all three collapse into one merged record and the translator is
lost. Turn those sources off in *Preferences → Metadata download* while
fetching Hungarian editions, and moly.hu's result stands on its own.

The download log tells you whether it happened. The last line reports how many
results survived merging:

```
Found 1 results        <- Moly.hu Reloaded, with "Translator : ..." in its block
...
We have 4 merged results
```

If moly.hu's own block lists the translator but the column stays empty, its
result was merged with another source's.

The calibre-web provider does not support this: its `MetaRecord` has no custom
column concept.

Include it in calibre-web docker yaml:
```
volumes:
  - moly_hu.py:/app/calibre-web/cps/metadata_provider/moly_hu.py:ro
  - moly_hu_provider.py:/app/calibre-web/cps/metadata_provider/moly_hu_provider.py:ro
```


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
