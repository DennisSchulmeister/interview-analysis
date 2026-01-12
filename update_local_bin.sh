#!/bin/sh
set -eu

LINK_DIR="${HOME}/.local/bin"
LINK_PATH="${LINK_DIR}/interview_analysis"

if ! command -v poetry >/dev/null 2>&1; then
  echo "error: poetry is not installed or not on PATH" >&2
  exit 1
fi

VENV_PATH="$(poetry env info --path | tail -n 1)"
if [ -z "${VENV_PATH}" ]; then
  echo "error: could not determine poetry virtualenv path" >&2
  exit 1
fi

TARGET_PATH="${VENV_PATH}/bin/interview_analysis"
if [ ! -e "${TARGET_PATH}" ]; then
  echo "error: expected target does not exist: ${TARGET_PATH}" >&2
  echo "hint: try 'poetry install' to create/update the venv" >&2
  exit 1
fi

mkdir -p "${LINK_DIR}"

# If the path exists and is a symlink (even broken), recreate it.
# If the path exists but is not a symlink, abort.
if [ -L "${LINK_PATH}" ]; then
  rm -f "${LINK_PATH}"
elif [ -e "${LINK_PATH}" ]; then
  echo "error: ${LINK_PATH} exists and is not a symlink; refusing to overwrite" >&2
  exit 1
fi

ln -s "${TARGET_PATH}" "${LINK_PATH}"

echo "ok: linked ${LINK_PATH} -> ${TARGET_PATH}"