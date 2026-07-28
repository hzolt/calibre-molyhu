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

The column must be of type **"Text, column shown in the Tag browser"** with
**"Contains names"** ticked. Calibre discards a downloaded custom column value
without any warning when the type does not match, so the plugin config checks
the column and warns; if the column does not exist yet, a button there creates
it (calibre has to be restarted afterwards, as for any new column).

Two limitations worth knowing:

- All edition-derived fields (publisher, ISBN, publication date, translator)
  are read from the **first** edition listed on the page, so they always
  describe the same edition.
- If another enabled metadata source returns a result with the same title and
  authors, calibre merges the two and rebuilds the record from standard fields
  only, dropping the translator. Downloading from moly.hu alone is unaffected.

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
