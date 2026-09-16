#!/usr/bin/env bash
# Build one of the three plugin zips out of the repository.
#
#   scripts/create_plugin_zip.sh <calibre|translator|calibreweb> <source repo path> [output file] [version]
#
# Each zip carries a copy of the shared scraper, moly_hu/src/moly_hu/moly_hu.py,
# next to the front end that uses it. The version is a "v1.2.3" tag: it is
# written into the calibre plugin's version tuple, and into a comment at the
# top of the calibre-web files.
set -euo pipefail

usage() {
    echo "Usage: ${0} <calibre|translator|calibreweb> <source repo path> [output file] [version]" >&2
    exit 2
}

[[ $# -ge 2 ]] || usage

readonly TARGET="$1"
readonly SOURCE_PATH="$(cd "$2" && pwd)"
readonly VERSION="${4:-v0.0.0}"

case "${TARGET}" in
    calibre)    default_output="Calibre_Moly_hu_Reloaded.zip" ;;
    translator) default_output="Calibre_Moly_hu_Translator.zip" ;;
    calibreweb) default_output="Calibreweb_Moly_hu.zip" ;;
    *) usage ;;
esac
readonly OUTPUT="${3:-${default_output}}"
# Made absolute, because the zip is written from inside a temporary directory.
readonly OUTPUT_FILE="$(cd "$(dirname "${OUTPUT}")" && pwd)/$(basename "${OUTPUT}")"

readonly SCRAPER="${SOURCE_PATH}/moly_hu/src/moly_hu/moly_hu.py"
readonly WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

# Write the tag into calibre's version tuple: "v1.2.3" -> (1, 2, 3). A tag
# without a patch number, "v3.2", still gives a whole tuple.
set_calibre_version() {
    local major minor patch
    IFS='.' read -r major minor patch <<< "${VERSION#v}"
    sed -i "s/version = (0, 0, 0)/version = (${major:-0}, ${minor:-0}, ${patch:-0})/" "$1"
}

case "${TARGET}" in
    calibre)
        cp "${SOURCE_PATH}/calibre/__init__.py" \
           "${SOURCE_PATH}/calibre/plugin-import-name-moly_hu_reloaded.txt" \
           "${SCRAPER}" "${SOURCE_PATH}/README.md" "${WORK_DIR}/"
        set_calibre_version "${WORK_DIR}/__init__.py"
        ;;
    translator)
        cp "${SOURCE_PATH}/calibre_translator/__init__.py" \
           "${SOURCE_PATH}/calibre_translator/action.py" \
           "${SOURCE_PATH}/calibre_translator/config.py" \
           "${SOURCE_PATH}/calibre_translator/plugin-import-name-moly_hu_translator.txt" \
           "${SCRAPER}" "${SOURCE_PATH}/README.md" "${WORK_DIR}/"
        mkdir -p "${WORK_DIR}/images"
        cp "${SOURCE_PATH}"/calibre_translator/images/*.png "${WORK_DIR}/images/"
        set_calibre_version "${WORK_DIR}/__init__.py"
        ;;
    calibreweb)
        cp "${SOURCE_PATH}/calibre-web/moly_hu.py" "${SOURCE_PATH}/README.md" "${WORK_DIR}/"
        # Under the name the provider imports the scraper by.
        cp "${SCRAPER}" "${WORK_DIR}/moly_hu_provider.py"
        sed -i "1s;^;# version: ${VERSION}\n\n;" "${WORK_DIR}/moly_hu.py" "${WORK_DIR}/moly_hu_provider.py"
        ;;
esac

# A fresh archive: zip would otherwise add to one left over from an earlier run.
rm -f "${OUTPUT_FILE}"
(cd "${WORK_DIR}" && zip -q -r "${OUTPUT_FILE}" .)
echo "${OUTPUT_FILE}"
