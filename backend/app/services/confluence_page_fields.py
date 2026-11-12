"""Source status badges and user mentions; source names never imply local approval."""
import re
from html import escape, unescape
from html.parser import HTMLParser


class _StatusTitle(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "ac:parameter":
            self.capture = dict(attrs).get("ac:name", "").lower() == "title"

    def handle_endtag(self, tag):
        if tag == "ac:parameter":
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def unknown_decl(self, data):
        if self.capture and data.startswith("CDATA["):
            self.parts.append(data[6:])


def status_html(block: str) -> str:
    parser = _StatusTitle()
    parser.feed(block)
    parser.close()
    title = "".join(parser.parts).strip()
    if not title:
        return "<em>Source status unavailable — see the original page</em>"
    return f"<span>{escape(title)}</span>"


def normalize_document_status(markdown: str) -> str:
    """Remove Confluence template prompt text only in a two-cell status row.

    Do not modify prose, examples, other cells, or the actual source status's case.
    Run after Markdown conversion so it also handles prompts outside badge macros.
    """
    row = re.compile(r"^(\|[ \t]*(?:\*\*|__)?Document[ \t]+status(?:\*\*|__)?[ \t]*\|)([^|]*)(\|[ \t]*)$", re.I)
    prompt = re.compile(r"^[ \t]*SET[ \t]+A[ \t]+STATUS(?:[ \t]+|$)", re.I)
    fence = None
    out = []
    for line in markdown.splitlines(keepends=True):
        text = line.rstrip("\r\n")
        ending = line[len(text):]
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", text)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence = (run[0], len(run))
            elif run[0] == fence[0] and len(run) >= fence[1] and not text[marker.end():].strip():
                fence = None
            out.append(line)
            continue
        match = row.fullmatch(text) if fence is None else None
        if match and prompt.match(match.group(2)):
            value = prompt.sub("", match.group(2), count=1).strip()
            if not value:
                value = "Source status unavailable — see the original page"
            text = match.group(1) + " " + value + " " + match.group(3)
            line = text + ending
        out.append(line)
    return "".join(out)


_USER_TAG = re.compile(r'<ri:user\b[^>]*?(?:/\s*>|>\s*</ri:user\s*>)', re.I | re.S)
_USER_LINK = re.compile(r'<ac:link\b[^>]*>(?:(?!</ac:link>).)*?</ac:link>', re.I | re.S)
_OPAQUE = re.compile(r'<(ac:plain-text-body|pre|code)\b[^>]*>.*?</\1\s*>|<!--.*?-->', re.I | re.S)


class _UserAttributes(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.attributes = {}

    def handle_starttag(self, tag, attrs):
        if tag == "ri:user":
            self.attributes = dict(attrs)


def user_identity(tag: str) -> tuple[str, str] | None:
    parser = _UserAttributes()
    parser.feed(tag)
    attrs = parser.attributes
    for attribute, parameter in (("ri:account-id", "accountId"), ("ri:userkey", "key"), ("ri:username", "username")):
        identifier = attrs.get(attribute)
        if isinstance(identifier, str) and identifier.strip():
            identifier = identifier.strip()
            if len(identifier) <= 512 and not re.search(r"[\x00-\x1f\x7f]", identifier):
                return parameter, identifier
    return None


def user_references(storage: str) -> list[tuple[str, str]]:
    # Stable order and one lookup per distinct identity.
    return list(dict.fromkeys(identity for match in _USER_TAG.finditer(_OPAQUE.sub("", storage))
                              if (identity := user_identity(match.group(0))) is not None))


def resolve_user_names(storage: str, session, base_url: str, cache: dict, json_reader,
                       on_warning=None, max_users: int = 256) -> dict:
    """Use the existing authenticated site session. Cache successes AND failures per run.

    Only display/public names are retained, never emails or complete profile responses.
    The endpoint is fixed; source markup only supplies a query parameter, not a URL.
    """
    names = {}
    for identity in user_references(storage):
        if identity not in cache:
            if len(cache) >= max_users:
                if on_warning:
                    on_warning("Confluence user lookup limit reached; unresolved mentions remain explicit.")
                continue
            cache[identity] = None
            try:
                response = session.get(f"{base_url.rstrip('/')}/rest/api/user",
                                       params={identity[0]: identity[1]}, allow_redirects=False)
                if response.status_code == 200:
                    person = json_reader(response)
                    if isinstance(person, dict):
                        # If the source supplies an identity, it must agree with the request.
                        field = {"accountId": "accountId", "key": "userKey", "username": "username"}[identity[0]]
                        returned = person.get(field)
                        if returned is None or str(returned) == identity[1]:
                            for key in ("displayName", "publicName"):
                                value = person.get(key)
                                if isinstance(value, str) and value.strip():
                                    cache[identity] = value.strip()
                                    break
            except Exception:
                # A missing/hidden profile must not abort a readable page's import.
                pass
        if cache.get(identity):
            names[identity] = cache[identity]
        elif on_warning:
            on_warning(f"Confluence user mention could not be resolved ({identity[0]}: {identity[1]}).")
    return names


def render_user_mentions(storage: str, names: dict | None = None) -> str:
    names = names or {}

    def render(match):
        identity = user_identity(match.group(0))
        name = names.get(identity) if identity else None
        if isinstance(name, str) and name.strip():
            return f"<span>{escape(name)}</span>"
        detail = f" ({identity[0]}: {identity[1]})" if identity else ""
        return f"<em>{escape('Unresolved Confluence user' + detail)}</em>"

    def linked_user(match):
        block = match.group(0)
        mentions = list(_USER_TAG.finditer(block))
        if len(mentions) == 1 and not re.search(r"<ri:(?:page|attachment)\b", block, re.I):
            # The mentioned person's visible name replaces the complete user link,
            # including any duplicate link-body caption, instead of rendering twice.
            return render(mentions[0])
        return block

    def convert(fragment):
        fragment = separate_document_owners(fragment)
        return _USER_TAG.sub(render, _USER_LINK.sub(linked_user, fragment))

    out = []
    offset = 0
    for match in _OPAQUE.finditer(storage):
        out.extend((convert(storage[offset:match.start()]), match.group(0)))
        offset = match.end()
    out.append(convert(storage[offset:]))
    return "".join(out)


def separate_document_owners(storage: str) -> str:
    """Separate adjacent source user references only in Document owner table cells.

    Names are not split on spaces: mention boundaries establish individual owners.
    Existing punctuation or words between owners are preserved.
    """
    rows = re.compile(r'<tr\b[^>]*>(?:(?!<tr\b).)*?</tr>', re.I | re.S)
    cells = re.compile(r'<(td|th)\b[^>]*>(.*?)</\1>', re.I | re.S)

    def convert_row(match):
        row = match.group(0)
        columns = list(cells.finditer(row))
        if len(columns) != 2:
            return row
        label = unescape(re.sub(r'<[^>]*>', ' ', columns[0].group(2)))
        if re.sub(r'\s+', ' ', label).strip().lower() != 'document owner':
            return row
        column = columns[1]
        value = column.group(2)
        linked = [m for m in _USER_LINK.finditer(value)
                  if len(list(_USER_TAG.finditer(m.group(0)))) == 1
                  and not re.search(r'<ri:(?:page|attachment)\b', m.group(0), re.I)]
        tokens = linked + [m for m in _USER_TAG.finditer(value)
                           if not any(link.start() <= m.start() < link.end() for link in linked)]
        tokens.sort(key=lambda m: m.start())
        for previous, following in reversed(list(zip(tokens, tokens[1:]))):
            gap = value[previous.end():following.start()]
            visible_gap = unescape(re.sub(r'<br\s*/?>', '', gap, flags=re.I))
            if not visible_gap.strip():
                value = value[:previous.end()] + ' - ' + value[following.start():]
        return row[:column.start(2)] + value + row[column.end(2):]

    return rows.sub(convert_row, storage)
