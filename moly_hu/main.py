import argparse
import urllib.request

import moly_hu.moly_hu as molyhu


def fetch_page(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; CalibreMolyhu/1.0)"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "search_for", type=str, help="What to search for eg: Raymond Feist Magus"
    )
    parser.add_argument(
        "-c", "--count", type=int, default=1,
        help="How many of the hits to show, best match first",
    )
    args = parser.parse_args()

    # The hits come in moly.hu's order, best match first, so the first --count
    # of them are the ones worth opening.
    for book_id in molyhu.search(args.search_for, fetch_page)[: args.count]:
        print(molyhu.book_for_id(book_id, fetch_page))


if __name__ == "__main__":
    main()
