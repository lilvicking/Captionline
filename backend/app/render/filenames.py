"""Download filename construction.

The name reaches an HTTP `Content-Disposition` header, so it is built from a
conservative allowlist rather than by stripping characters. A path separator, a
quote, a control character, or a shell metacharacter cannot survive, and the
result is length-bounded.
"""

from __future__ import annotations

import re

#: Letters, digits, dot, underscore and hyphen only. Everything else is dropped.
_ALLOWED = re.compile(r"[^A-Za-z0-9._-]+")

#: Reserved DOS/Windows device names, which are unsafe as filenames.
_RESERVED = {
    "con", "prn", "aux", "nul",
    *{f"com{index}" for index in range(1, 10)},
    *{f"lpt{index}" for index in range(1, 10)},
}

MAX_STEM_LENGTH = 80
SUFFIX = "-captioned.mp4"


def build_output_filename(original: str) -> str:
    """Turn a client-supplied name into `<stem>-captioned.mp4`.

    `original` may be a full path or contain anything at all; the allowlist
    guarantees the result is inert wherever it is later used.
    """
    # Take the basename first so a path in the input cannot influence anything.
    candidate = original.replace("\\", "/").split("/")[-1]
    stem = candidate.rsplit(".", 1)[0] if "." in candidate else candidate

    cleaned = _ALLOWED.sub("-", stem).strip("-._")
    cleaned = cleaned[:MAX_STEM_LENGTH].strip("-._")

    if not cleaned:
        cleaned = "video"

    if cleaned.casefold() in _RESERVED:
        cleaned = f"{cleaned}-file"

    return f"{cleaned}{SUFFIX}"
