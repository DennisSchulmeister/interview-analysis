# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""Hash utilities.

The project uses MD5 hashes only for change detection of intermediate work files.
It is not used for cryptographic security.
"""

from pathlib import Path
import hashlib


def md5_file(path: Path) -> str:
    """Compute an MD5 hash for a file.

    Args:
        path:
            File path.

    Returns:
        Lowercase hex MD5 digest.
    """

    # Some environments run in FIPS mode. Python's hashlib supports
    # `usedforsecurity=False` for legacy hashes on OpenSSL-backed builds.
    try:
        hasher = hashlib.md5(usedforsecurity=False)  # type: ignore[call-arg]
    except TypeError:
        hasher = hashlib.md5()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)

    return hasher.hexdigest()
