"""sealed_data.py -- read a data-branch file that is published sealed (seal move 3, 2026-11-11).

The repo is public, so the files that name tonight's calls go out only as <name>.sealed
(.github/scripts/seal_data.sh; the list below is the same list). A reader in this repo that fetches one over
https uses this module: it asks for the sealed copy, checks it and opens it with DATA_SEAL_KEY.

  sealed_url(url)        the url to ask for (adds .sealed when the file is on the list, else unchanged)
  open_body(body)        the plain bytes of a fetched body (unchanged when it is not a sealed file)
  urlopen_read(url)      urllib: fetch + open; 404 only when neither the sealed nor the plain copy exists
  requests_get(url)      requests: the same, returns the Response with the opened body

A sealed file that cannot be opened (no key in this step, wrong key, changed file) raises SealError. It is never
reported as a missing file: several callers start a fresh ledger on a 404.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import subprocess
import urllib.error
import urllib.request

# keep in step with SEALED_RE in .github/scripts/seal_data.sh (tests/test_seal_data.py compares the two)
SEALED_RE = re.compile(
    r"^(nfl_(next_)?(week|game_calls|picks)\.json|(today|tomorrow)_slim\.json|results_live\.json|pick_changes\.json"
    r"|pair_builder_latest\.json|nfl_pick_lock\.json|pick_lock\.json|nhl_board_latest\.json|nba_board_latest\.json"
    r"|nba_first_board_latest\.json|nfl_(next_)?picks_[0-9]{4}_w[0-9]{2}\.json|nfl_td_log_[0-9]{4}\.jsonl"
    r"|nfl_game_calls_log_[0-9]{4}_w[0-9]{2}\.jsonl|por_rows_[0-9]{4}-[0-9]{2}-[0-9]{2}\.jsonl)$"
)
MAGIC = b"DSEAL1."


class SealError(RuntimeError):
    """A sealed file is there and could not be opened."""


def is_sealed_name(name: str) -> bool:
    return bool(SEALED_RE.match(name.rsplit("/", 1)[-1]))


def sealed_url(url: str) -> str:
    path, sep, query = url.partition("?")
    return f"{path}.sealed{sep}{query}" if is_sealed_name(path) else url


def _keys() -> tuple[str, bytes]:
    key = os.environ.get("DATA_SEAL_KEY", "")
    if not re.fullmatch(r"[0-9a-fA-F]{128}", key):
        raise SealError("DATA_SEAL_KEY is not set in this step, so a sealed data file cannot be opened")
    return key[:64], bytes.fromhex(key[64:])


def unseal(body: bytes) -> bytes:
    enc, mac = _keys()
    try:
        version, iv, tag, ct = body.strip().decode("ascii").split(".", 3)
    except Exception as e:
        raise SealError("not a sealed file") from e
    if version != "DSEAL1":
        raise SealError("not a sealed file")
    want = hmac.new(mac, f"tag|{iv}.{ct}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, tag):
        raise SealError("sealed file failed its check (wrong key or changed)")
    try:
        out = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-K", enc, "-iv", iv],
                             input=base64.b64decode(ct), capture_output=True, check=True)
    except Exception as e:
        raise SealError(f"sealed file could not be decrypted ({type(e).__name__})") from e
    return out.stdout


def open_body(body: bytes) -> bytes:
    return unseal(body) if body[:len(MAGIC)] == MAGIC else body


def urlopen_read(url, timeout: float = 20, headers: dict | None = None) -> bytes:
    """Fetch url (a str) and return its plain bytes. Raises what urllib raises; HTTPError 404 means absent."""
    def get(u: str) -> bytes:
        req = urllib.request.Request(u, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    s = sealed_url(url)
    if s == url:
        return get(url)
    try:
        return open_body(get(s))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    return open_body(get(url))


def requests_get(url: str, **kw):
    """requests.get for a data-branch file: the Response carries the opened body. A 404 is the Response as it came."""
    import requests
    s = sealed_url(url)
    if s == url:
        return requests.get(url, **kw)
    r = requests.get(s, **kw)
    if r.status_code == 404:
        return requests.get(url, **kw)
    if r.status_code == 200:
        r._content = open_body(r.content)
        r.encoding = "utf-8"
    return r
