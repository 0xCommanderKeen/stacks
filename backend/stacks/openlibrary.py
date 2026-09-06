"""One optional provider: bounded, owner-triggered Open Library suggestions."""

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

LIMIT = 256 * 1024
KEY = re.compile(r"/works/OL[0-9]{1,12}W\Z")


class ProviderUnavailable(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderUnavailable("The metadata provider redirected the request; try again later.")


def fetch(path, contact=""):
    """Call only fixed provider paths; callers never supply an arbitrary URL."""
    if not (
        path.startswith("/search.json?") or (path.endswith(".json") and KEY.fullmatch(path[:-5]))
    ):
        raise ProviderUnavailable("Invalid metadata lookup.")
    agent = "Stacks/0.1 (+https://github.com/0xCommanderKeen/stacks)"
    if contact:
        if len(contact) > 128 or not contact.isascii() or any(ord(c) < 32 for c in contact):
            raise ProviderUnavailable("Invalid configured provider contact.")
        agent += f" ({contact})"
    request = Request(
        "https://openlibrary.org" + path,
        headers={
            "User-Agent": agent,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=8) as response:
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise ProviderUnavailable("The metadata provider returned unsupported encoding.")
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ProviderUnavailable("The metadata response exceeded its size limit.")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (HTTPError, URLError, OSError, ValueError) as exc:
        if isinstance(exc, ProviderUnavailable):
            raise
        raise ProviderUnavailable(
            "Open Library is unavailable or returned invalid metadata. Try again later."
        ) from None


def short(value, maximum):
    return value[:maximum] if isinstance(value, str) else ""


def lookup(request):
    contact = request.get("contact", "")
    if request["kind"] == "search":
        query = request["q"]
        offset = request.get("offset", 0)
        if not isinstance(query, str) or not 1 <= len(query) <= 300 or not 0 <= offset <= 10000:
            raise ProviderUnavailable("Invalid metadata search.")
        data = fetch(
            "/search.json?"
            + urlencode(
                {
                    "q": query,
                    "limit": 5,
                    "offset": offset,
                    "fields": "key,title,author_name",
                }
            ),
            contact,
        )
        documents = data.get("docs")
        if not isinstance(documents, list):
            raise ProviderUnavailable("Open Library returned an invalid search response.")
        matches = []
        for document in documents[:5]:
            if not isinstance(document, dict):
                continue
            key = document.get("key", "")
            if not isinstance(key, str) or not KEY.fullmatch(key):
                continue
            title = short(document.get("title"), 1024)
            authors = document.get("author_name", [])
            if not isinstance(authors, list):
                authors = []
            authors = [
                short(author, 512)
                for author in authors[:50]
                if isinstance(author, str) and author.strip()
            ]
            if title:
                matches.append({"key": key, "title": title, "authors": authors})
        total = data.get("numFound", data.get("num_found", 0))
        return {
            "matches": matches,
            "total": max(0, total) if isinstance(total, int) else len(matches),
        }
    key = request.get("key", "")
    if request["kind"] != "details" or not isinstance(key, str) or not KEY.fullmatch(key):
        raise ProviderUnavailable("Invalid metadata lookup.")
    data = fetch(key + ".json", contact)
    description = data.get("description", "")
    if isinstance(description, dict):
        description = description.get("value", "")
    return {"description": short(description, 20000)}


class OpenLibrary:
    def __init__(self, contact=""):
        self.contact = contact
        self.lock = threading.Lock()
        self.next_request = 0.0

    def request(self, **payload):
        if not self.lock.acquire(blocking=False):
            raise ProviderUnavailable("A metadata lookup is already running. Try again shortly.")
        try:
            if time.monotonic() < self.next_request:
                raise ProviderUnavailable("Wait a moment before another metadata lookup.")
            self.next_request = time.monotonic() + 1.0
            payload["contact"] = self.contact
            with subprocess.Popen(
                [sys.executable, "-m", "stacks.openlibrary"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            ) as child:
                try:
                    output, _ = child.communicate(json.dumps(payload).encode(), timeout=12)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.communicate()
                    raise ProviderUnavailable("Open Library timed out. Try again later.") from None
            if child.returncode or len(output) > LIMIT:
                raise ProviderUnavailable("Open Library returned an invalid response.")
            try:
                value = json.loads(output)
            except ValueError:
                raise ProviderUnavailable("Open Library returned an invalid response.") from None
            if "error" in value:
                raise ProviderUnavailable(value["error"])
            return value
        finally:
            self.lock.release()


if __name__ == "__main__":
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2, 256 * 1024**2))
    try:
        print(json.dumps(lookup(json.loads(sys.stdin.buffer.read(4096)))))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": str(exc)
                    if isinstance(exc, ProviderUnavailable)
                    else "Metadata lookup failed."
                }
            )
        )
