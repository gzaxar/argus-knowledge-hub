"""A wiki's pages as documents: one page by its link, or the page and every page under it (its namespace).

DokuWiki (wiki.infn.it) is read through what it shows anyone allowed to read it: a page's content alone
(`?do=export_xhtmlbody`), a namespace's index (`?do=index`) and its pictures (`/_media/…`) — its API is often off.
What is fetched becomes a folder like a saved web page — each page's HTML, its pictures beside it, links between
the pages made relative — and is imported as any web page folder is (services/web_import.py): one document per
page, its pictures shown in place, its HTML kept as the original, and where it came from (its link) recorded.

Only wikis on the hosts allowed (ARGUS_WIKI_HOSTS, comma-separated; wiki.infn.it unless set) are fetched, over
https, redirects included: a link given cannot make the server read anything else.
"""
from __future__ import annotations

import html
import json
import os
import posixpath
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

import requests

MAX_PAGES = 30
MAX_PICTURE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
TIMEOUT = 20
AGENT = "ARGUS-Knowledge-Hub wiki import"


class WikiError(ValueError):
    pass


def allowed_hosts() -> set[str]:
    raw = os.environ.get("ARGUS_WIKI_HOSTS", "wiki.infn.it")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _check(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise WikiError("Only https wiki links are imported.")
    host = (parts.hostname or "").lower()
    if host not in allowed_hosts():
        raise WikiError(f"{host or 'That link'} is not a wiki ARGUS may import from "
                        f"(allowed: {', '.join(sorted(allowed_hosts()))}).")
    return url


def get(url: str, *, limit: int = 5 * 1024 * 1024) -> requests.Response:
    """A GET to an allowed wiki, following at most 3 redirects, each checked."""
    for _ in range(4):
        _check(url)
        r = requests.get(url, timeout=TIMEOUT, allow_redirects=False, stream=True, headers={"User-Agent": AGENT})
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            r.close()
            continue
        content = b""
        for chunk in r.iter_content(64 * 1024):
            content += chunk
            if len(content) > limit:
                r.close()
                raise WikiError("A file of the wiki is too large to import.")
        r._content = content
        if r.status_code in (401, 403):
            raise WikiError("The wiki asks to sign in for that page: only pages anyone may read are imported.")
        if r.status_code == 404:
            raise WikiError("The wiki has no such page.")
        if r.status_code >= 400:
            raise WikiError(f"The wiki answered {r.status_code}.")
        return r
    raise WikiError("The wiki redirected too many times.")


@dataclass
class Wiki:
    origin: str                 # https://wiki.infn.it
    base: str                   # DOKU_BASE: "/" or "/wiki/"
    page_id: str                # strutture:lnf:da:btf:dispositivi:stages
    url: str

    def doku(self, page_id: str, **params) -> str:
        query = "&".join(f"{k}={quote(str(v), safe=':')}" for k, v in params.items())
        return f"{self.origin}{self.base}doku.php?id={quote(page_id, safe=':')}" + (f"&{query}" if query else "")

    def page_url(self, page_id: str) -> str:
        return self.doku(page_id)


def open_wiki(url: str) -> Wiki:
    """The wiki and the page a link names (a DokuWiki page, in any of its link forms)."""
    url = (url or "").strip()
    if not url:
        raise WikiError("Give the link of a wiki page.")
    r = get(_check(url))
    text = r.text
    if not re.search(r'<meta name="generator" content="DokuWiki', text, re.I):
        raise WikiError("Only DokuWiki pages can be imported for now.")
    m = re.search(r"DOKU_BASE\s*=\s*['\"]([^'\"]*)['\"]", text)
    base = m.group(1) if m else "/"
    m = re.search(r"JSINFO\s*=\s*(\{.*?\});", text, re.S)
    page_id = None
    if m:
        try:
            page_id = json.loads(m.group(1)).get("id")
        except ValueError:
            page_id = None
    if not page_id:
        q = parse_qs(urlsplit(url).query)
        page_id = (q.get("id") or [None])[0] or unquote(urlsplit(url).path).strip("/").replace("/", ":")
    parts = urlsplit(r.url)
    return Wiki(origin=f"{parts.scheme}://{parts.netloc}", base=base if base.endswith("/") else base + "/",
                page_id=page_id, url=url)


# --------------------------------------------------------------------------- what a namespace holds

class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[dict, str]] = []
        self._open: Optional[dict] = None
        self._text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._open, self._text = dict(attrs), ""

    def handle_data(self, data):
        if self._open is not None:
            self._text += data

    def handle_endtag(self, tag):
        if tag == "a" and self._open is not None:
            self.links.append((self._open, self._text.strip()))
            self._open = None


def namespace_pages(wiki: Wiki, namespace: str, limit: int = MAX_PAGES) -> tuple[list[tuple[str, str]], bool]:
    """([(page id, name)], truncated): the pages in `namespace` and the namespaces under it, the namespace's own
    page (the one of the same name) first."""
    pages: dict[str, str] = {}
    queue, seen = [namespace], set()
    truncated = False
    while queue:
        ns = queue.pop(0)
        if ns in seen:
            continue
        seen.add(ns)
        parser = _Links()
        parser.feed(get(wiki.doku(ns, do="index", idx=ns)).text)
        for attrs, text in parser.links:
            wid = attrs.get("data-wiki-id") or ""
            cls = attrs.get("class") or ""
            if "idx_dir" in cls:
                sub = (parse_qs(urlsplit(html.unescape(attrs.get("href") or "")).query).get("idx") or [""])[0]
                if sub.startswith(ns + ":") and sub not in seen:
                    queue.append(sub)
            elif wid and (wid == namespace or wid.startswith(ns + ":") and ":" not in wid[len(ns) + 1:]):
                if wid not in pages:
                    if len(pages) >= limit:
                        truncated = True
                        break
                    pages[wid] = text or wid.rsplit(":", 1)[-1]
        if truncated:
            break
    ordered = sorted(pages.items(), key=lambda kv: (kv[0] != namespace, kv[0]))
    return ordered, truncated


# --------------------------------------------------------------------------- the pages, as a folder

def path_of(page_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:\-]", "_", page_id).replace(":", "/") + ".html"


def _media_path(wiki: Wiki, src: str) -> Optional[tuple[str, str]]:
    """(the picture's full-size URL, its path in the folder), for a picture of this wiki."""
    absolute = urljoin(wiki.origin + wiki.base, html.unescape(src))
    parts = urlsplit(absolute)
    if f"{parts.scheme}://{parts.netloc}" != wiki.origin:
        return None
    path = unquote(parts.path)
    if "/_media/" in path:
        media = path.split("/_media/", 1)[1]
        full = f"{wiki.origin}{wiki.base}_media/{quote(media)}"
    elif path.endswith("lib/exe/fetch.php"):
        media = (parse_qs(parts.query).get("media") or [""])[0].replace(":", "/")
        full = f"{wiki.origin}{wiki.base}lib/exe/fetch.php?media={quote(media.replace('/', ':'), safe=':')}"
    else:
        return None
    media = re.sub(r"[^A-Za-z0-9_.\-/]", "_", media.replace(":", "/")).lstrip("/")
    return (full, "media/" + media) if media else None


def _attr(tag: str, name: str) -> Optional[str]:
    m = re.search(rf'\s{name}\s*=\s*"([^"]*)"', tag) or re.search(rf"\s{name}\s*=\s*'([^']*)'", tag)
    return m.group(1) if m else None


def _set_attr(tag: str, name: str, value: str) -> str:
    value = html.escape(value, quote=True)
    if _attr(tag, name) is not None:
        return re.sub(rf'(\s{name}\s*=\s*)("[^"]*"|\'[^\']*\')', lambda m: f'{m.group(1)}"{value}"', tag, count=1)
    return tag[:-1] + f' {name}="{value}">'


def fetch_bodies(wiki: Wiki, ids: list[str]) -> dict[str, str]:
    """Each page's content (its HTML without the wiki's menus), fetched six at a time."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(zip(ids, pool.map(lambda i: get(wiki.doku(i, do="export_xhtmlbody")).text, ids)))


def build_folder(wiki: Wiki, ids: list[str], bodies: Optional[dict[str, str]] = None,
                 linkable: Optional[set[str]] = None,
                 max_pages: int = MAX_PAGES) -> tuple[dict[str, bytes], dict[str, dict]]:
    """({path: content}, {page path: where it came from}) for the pages `ids`, with their pictures. A link to a
    page of `linkable` (the pages being imported, `ids` unless said) is made relative, to lead to its document."""
    if len(ids) > max_pages:
        raise WikiError(f"At most {max_pages} pages at a time.")
    wanted = set(linkable if linkable is not None else ids)
    bodies = bodies if bodies is not None else fetch_bodies(wiki, ids)
    bodies = {i: bodies[i] for i in ids}
    folder: dict[str, bytes] = {}
    sources: dict[str, dict] = {}
    pictures: dict[str, str] = {}               # folder path -> full-size URL
    for page_id, body in bodies.items():
        path = path_of(page_id)
        here = posixpath.dirname(path)

        def img(m):
            tag = m.group(0)
            found = _media_path(wiki, _attr(tag, "src") or "")
            if not found:
                return tag
            full, media = found
            pictures.setdefault(media, full)
            return _set_attr(tag, "src", posixpath.relpath(media, here or "."))

        def link(m):
            tag = m.group(0)
            target = _attr(tag, "data-wiki-id")
            href = html.unescape(_attr(tag, "href") or "")
            cls = _attr(tag, "class") or ""
            if target and target in wanted:
                return _set_attr(tag, "href", posixpath.relpath(path_of(target), here or "."))
            if "/_detail/" in href or "wikilink2" in cls or "media" in cls.split():
                return _set_attr(tag, "href", "#")      # a picture's details page, a page that does not exist
            if href.startswith("/"):
                return _set_attr(tag, "href", wiki.origin + href)
            return tag
        body = re.sub(r"<img\b[^>]*>", img, body, flags=re.I)
        body = re.sub(r"<a\b[^>]*>", link, body, flags=re.I)
        folder[path] = f"<html><head><meta charset=\"utf-8\"></head><body>{body}</body></html>".encode("utf-8")
        sources[path] = {"argus_source_url": wiki.page_url(page_id), "argus_source_id": page_id}

    def fetch(item):
        media, url = item
        try:
            return media, get(url, limit=MAX_PICTURE_BYTES).content
        except (WikiError, requests.RequestException):
            return media, None                  # the page keeps the picture's description
    total = sum(len(c) for c in folder.values())
    with ThreadPoolExecutor(max_workers=6) as pool:
        for media, content in pool.map(fetch, pictures.items()):
            if content is None:
                continue
            total += len(content)
            if total > MAX_TOTAL_BYTES:
                raise WikiError(f"The pages and their pictures are larger than {MAX_TOTAL_BYTES // (1024 * 1024)} MB: "
                                "import fewer at a time.")
            folder[media] = content
    return folder, sources
