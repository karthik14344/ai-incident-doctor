"""Log signatures - the doctor's own copy of the patient's algorithm.

The patient stamps `log_signature` on its structured exception lines. Lines
that are not structured (a plain `print`, a crash before logging was set up)
carry none, so the doctor computes one itself with the same normalisation.

Kept as a copy on purpose (DECISIONS.md D-1): the doctor must keep working when
the patient is broken, so it imports nothing from it. A test asserts the two
implementations agree.
"""

import hashlib
import re

_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b|\b(?=[0-9a-fA-F]*[0-9])(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{8,}\b")
_PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][\w.\-]+){2,}[\\/]?")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_SPACE = re.compile(r"\s+")


def normalise_message(message: str) -> str:
    text = str(message or "")
    text = _UUID.sub("<uuid>", text)
    text = _PATH.sub("<path>", text)
    text = _HEX.sub("<hex>", text)
    text = _NUM.sub("<n>", text)
    return _SPACE.sub(" ", text).strip()


def signature(exc_type: str, message: str) -> str:
    digest = hashlib.sha1(f"{exc_type}|{normalise_message(message)}".encode("utf-8")).hexdigest()
    return f"{exc_type}:{digest[:12]}"
