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
| **Moly.hu Translator** | `scripts/create_calibre_translator_plugin_zip.sh` | calibre toolbar button that writes the translator, rating, rating count, statistics page URL and ebook marker into custom columns |
| **calibre-web provider** | `scripts/create_calibreweb_plugin_zip.sh` | the same metadata for calibre-web |

The two calibre plugins are separate because calibre loads exactly one plugin
class per zip (`plugin_classes[0]` in `calibre/customize/zipplugin.py`), and
because they need different things from calibre: a metadata source runs in a
worker with no library handle, while writing a custom column needs the
library. Install both if you want the translator.

### Editions

A moly.hu book page lists every edition it knows of, each with its own
publisher, publication date, ISBN, page count and translator.

Where the page has an ebook edition, that is the edition the metadata
describes: it is the one a calibre library actually holds, and it is a release
of its own, with its own ISBN and often its own publication date. moly.hu
marks it on the edition line with a reader icon labelled *Ekönyv* and tags the
edition `ekönyv`:

```html
<div id="edition_840757" class="edition edition_840757">
  <div><a href="/kiadok/metropolis-media">Metropolis Media</a>, Budapest, 2023
    <img src=".../e-book-reader-black.png" data-title="Ekönyv" title="Ekönyv"/></div>
  <div>352 oldal · <strong>ISBN</strong>: 9789635511235 · ...</div>
  <a class="tag" href="/cimkek/ekonyv">ekönyv</a>
</div>
```

All three markings are matched (`data-title`, the older `title` spelling and
the tag link), because moly.hu does not render them consistently.

Hungarian ebook editions are thinly documented, though. The line above states
a bare `2023` where the printed edition of the same book carries
`Megjelenés időpontja: 2023. február 18.` in a tooltip, and an ebook line can
omit the publisher, the translator or even the ISBN. So the printed editions
fill in for it, field by field:

| | |
|---|---|
| **Publisher, translator** | taken from the ebook line; where it does not state them, from a printed edition |
| **Publication date** | the ebook's own date, sharpened by a printed edition's more precise one - but only where the two agree on every part the ebook states, so a 2017 ebook can never be given a 2015 hardback's day, and *2023. február* is never sharpened by a March date |
| **ISBN** | the ebook's own number; where its line states none, the printed edition's, because a record with the paperback's ISBN still names the book where a record with none names nothing |

The edition of the ebook's own publisher fills in first, being the most likely
to describe the same release; the rest follow in page order.

Filling in is for the ebook edition alone. On a page whose editions are all
printed, the first one is read on its own, so that a book with an old and a
re-translated edition cannot end up with the year of one and the translator of
another.

`Book.isbns()` lists the ISBN of every edition on the page whatever was read.
A library holding the paperback still confirms as a match against a page read
off the ebook edition, and the metadata source caches all of them, so a search
by the paperback's ISBN still finds the book.

### Moly.hu Translator

Adds a **Fetch data from moly.hu** toolbar button. Select books, press it, and
five values off the moly.hu book page are written into custom columns with
`db.new_api.set_field`:

| Field | Default column | What it holds |
|---|---|---|
| Translator | `#translator` | the names behind the edition's "Fordította" label |
| Rating | `#moly_rating` | the score as moly.hu shows it, a percentage from 0 to 100 (`94%` → `94`) |
| Rating count | `#moly_rating_count` | how many people rated it, from the "62 csillagozás" link |
| Statistics URL | `#moly_stats_raw` | the book's `/statisztika` page, e.g. `https://moly.hu/konyvek/dennis-e-taylor-mi-bob/statisztika`, for a book that has been rated |
| Type | `#type` | 📱 where the data was read off an ebook edition |

The rating is kept as the percentage rather than as calibre's 0-5 stars, which
cannot tell 90% from 94%. The metadata source plugin still fills calibre's own
rating field with the rounded 0-5 value; these columns are separate from it.

The statistics URL costs no extra page open: the book page links to it from
the "csillagozás" anchor, and where a rated book does not render that anchor
the address follows from the book's id. A book nobody has rated has no
statistics page at all - it only exists once there is a rating to break down -
so nothing is written for it rather than a guessed dead link. In a short text
column calibre renders the URL as a clickable link in *Book details*.

Set the columns in *Preferences → Plugins → Moly.hu Translator*. Any column
type works: the value is shaped to fit whatever is there, because calibre
rejects a value whose datatype does not match the column, and a column's type
cannot be changed once it has been created. Leaving a column blank, or naming
one that does not exist in the library, simply skips that field; the run only
refuses to start when none of them resolve.

Each field is written on its own, so a book whose page carries a rating but no
translator still gets its rating.

### The type marker

A book whose moly.hu page carries an ebook edition is marked in the type
column, because that is the edition the data was read from (see
[Editions](#editions) above). Unicode has no e-reader or Kindle glyph, so 📱 -
the device most of these files are read on - stands in for one, and calibre
renders it in the column like any other text.

The mark is a setting of its own, next to the column name in *Preferences →
Plugins → Moly.hu Translator*, so a library that would rather see 📖, 🖥 or the
word `ekönyv` only has to type it in. Emptying it turns the mark off without
having to unset the column.

Nothing is written for a page with printed editions only: calibre knows which
formats the library actually holds, moly.hu only knows what was published, so
an unmarked book is one moly.hu has no ebook edition for rather than one that
is certainly paper.

A book is only written when the moly.hu page is confirmed to be the right one,
by a matching ISBN or a matching title. `search()` returns an unordered set of
hits - a title search answers with the author's whole back catalogue - so
taking one on trust would file another book's data. Books that cannot be
confirmed are reported as not found instead.

### Subtitles

moly.hu often files a book under the first part of its title and shows the rest
as a subtitle of its own: *A pénz istenei: A Wall Street összeesküvése Amerika
leigázására* is held there as **A pénz istenei**. A search for the whole title
finds nothing, so `generate_search_terms()` also tries the part before each
colon or dash - after the whole title, so the more specific search always runs
first - and the title check accepts a page whose title is the library title cut
short at a separator, or the other way round. Only a full title is compared
with a shortened one; two shortened titles are not, or *Aliens: Föld ostroma*
would match *Aliens: A végső háború*. The separator has to carry a space (a
colon before one, a dash on both sides), which keeps *Aliens-gyűjtemény* and
*20:00* whole.

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
