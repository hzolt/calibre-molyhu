# Moly.hu Metadata source

Based on Hokutya's [moly.hu calibre plugin](https://www.mobileread.com/forums/showthread.php?t=193302) from mobileread.com.

Metadata from https://moly.hu

Supported applications:
- [calibre](https://calibre-ebook.com/)
- [calibre-web](https://github.com/janeczku/calibre-web)

## Usage

Search for book in command-line: `python -m moly_hu.main "raymond feist"`

### Translator custom column (calibre only)

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
