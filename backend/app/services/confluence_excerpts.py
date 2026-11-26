"""Resolve Confluence excerpt-include macros with the import's existing identity.

Only named/unnamed excerpt bodies are included, never the whole source page.
No network destination is taken from imported content. A bounded resolver lives
for one import job; failures remain visible rather than silently removing data.
"""
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
import re


@dataclass
class Macro:
    name: str
    start: int
    end: int = 0
    params: dict = field(default_factory=dict)
    page: dict = field(default_factory=dict)
    body_start: int = 0
    body_end: int = 0
    parameter: str | None = None
    parameter_text: list = field(default_factory=list)


class _Macros(HTMLParser):
    def __init__(self, storage):
        super().__init__(convert_charrefs=True)
        self.storage = storage
        self.offsets = [0]
        for line in storage.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.stack = []
        self.macros = []
        self.feed(storage)
        self.close()

    def source_offset(self):
        row, column = self.getpos()
        return self.offsets[row - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'ac:structured-macro':
            self.stack.append(Macro(attrs.get('ac:name', '').lower(), self.source_offset()))
        elif self.stack:
            macro = self.stack[-1]
            if tag == 'ac:parameter':
                macro.parameter = attrs.get('ac:name', '')
                macro.parameter_text = []
            elif tag == 'ri:page':
                macro.page = attrs
            elif tag in {'ac:rich-text-body', 'ac:plain-text-body'}:
                macro.body_start = self.source_offset() + len(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag, self_closing=True)

    def handle_endtag(self, tag, self_closing=False):
        if not self.stack:
            return
        macro = self.stack[-1]
        if tag == 'ac:parameter':
            if macro.parameter is not None:
                macro.params[macro.parameter] = ''.join(macro.parameter_text).strip()
                macro.parameter = None
        elif tag in {'ac:rich-text-body', 'ac:plain-text-body'}:
            macro.body_end = self.source_offset()
        elif tag == 'ac:structured-macro':
            self.stack.pop()
            macro.end = self.source_offset() + (len(self.get_starttag_text()) if self_closing else len('</ac:structured-macro>'))
            self.macros.append(macro)

    def handle_data(self, data):
        if self.stack and self.stack[-1].parameter is not None:
            self.stack[-1].parameter_text.append(data)


def _reference(macro):
    return (macro.page.get('ri:content-title', '').strip(),
            macro.page.get('ri:space-key', '').strip(),
            macro.params.get('name', '').strip(),
            macro.page.get('ri:content-id', '').strip())


def missing_excerpt(block):
    macros = [m for m in _Macros(block).macros if m.name == 'excerpt-include']
    title, _, name, _ = _reference(macros[0]) if macros else ('', '', '', '')
    label = ' | '.join(part for part in (title, name) if part) or 'unspecified source'
    return '<p><em>[Confluence excerpt unavailable: ' + escape(label) + ' — see the original page]</em></p>'


class ExcerptResolver:
    MAX_DEPTH = 5
    MAX_FETCHES = 50
    MAX_PAGE_CHARS = 500_000
    MAX_EXPANSION_CHARS = 500_000

    def __init__(self, fetch_page, on_warning=None):
        self.fetch_page = fetch_page
        self.on_warning = on_warning or (lambda reason: None)
        self.cache = {}
        self.fetches = 0

    def resolve(self, storage, space_key, page_id='', _chain=(), _depth=0):
        remaining = self.MAX_EXPANSION_CHARS
        macros = [m for m in _Macros(storage).macros if m.name == 'excerpt-include']
        # Include macros have no rich body; ignore malformed overlapping spans.
        chosen = []
        last = -1
        for macro in sorted(macros, key=lambda m: m.start):
            if macro.start >= last:
                chosen.append(macro)
                last = macro.end
        replacements = []
        for macro in chosen:
            block = storage[macro.start:macro.end]
            title, target_space, name, uid = _reference(macro)
            target_space = target_space or space_key
            reason = ''
            value = ''
            try:
                if _depth >= self.MAX_DEPTH:
                    raise ValueError('excerpt_depth_limit')
                if not title and not uid:
                    raise ValueError('excerpt_source_missing')
                key = (target_space, title, uid)
                if key not in self.cache:
                    if self.fetches >= self.MAX_FETCHES:
                        raise ValueError('excerpt_fetch_limit')
                    self.fetches += 1
                    try:
                        self.cache[key] = self.fetch_page(target_space, title, uid)
                    except Exception:
                        self.cache[key] = None
                page = self.cache[key]
                if not page:
                    raise ValueError('excerpt_page_unavailable')
                source = ((page.get('body') or {}).get('storage') or {}).get('value')
                if not isinstance(source, str):
                    raise ValueError('excerpt_storage_missing')
                if len(source) > self.MAX_PAGE_CHARS:
                    raise ValueError('excerpt_page_size_limit')
                identity = (str(page.get('id') or uid or title), name)
                if identity in _chain:
                    raise ValueError('excerpt_cycle')
                matches = [m for m in _Macros(source).macros if m.name == 'excerpt'
                           and m.params.get('name', '').strip() == name]
                if len(matches) != 1:
                    raise ValueError('excerpt_not_found_or_ambiguous')
                excerpt = matches[0]
                if not excerpt.body_start or excerpt.body_end < excerpt.body_start:
                    raise ValueError('excerpt_body_missing')
                fragment = source[excerpt.body_start:excerpt.body_end]
                # File ownership must not be confused with attachments on the
                # receiving page. A visible fallback is safer than a wrong file.
                if re.search(r'<(?:ri:attachment|ac:image)\b', fragment, re.I):
                    raise ValueError('excerpt_attachments_not_supported')
                source_space = (page.get('space') or {}).get('key') or target_space
                fragment = self.resolve(fragment, source_space, identity[0],
                                        _chain + (identity,), _depth + 1)
                if macro.params.get('nopanel', '').lower() == 'true':
                    value = fragment
                else:
                    label = ' | '.join(x for x in (page.get('title') or title, name) if x)
                    value = '<div><p><strong>' + escape(label) + '</strong></p>' + fragment + '</div>'
                if len(value) > remaining:
                    raise ValueError('excerpt_expansion_size_limit')
                remaining -= len(value)
            except ValueError as exc:
                reason = str(exc)
            except Exception:
                reason = 'excerpt_resolution_failed'
            if reason:
                self.on_warning(reason)
                value = missing_excerpt(block)
            replacements.append((macro.start, macro.end, value))
        for start, end, value in reversed(replacements):
            storage = storage[:start] + value + storage[end:]
        return storage


def authenticated_resolver(session, base_url, read_json, on_warning=None):
    """Use the configured Confluence session, never an imported URL or new token."""
    def fetch(space, title, uid):
        params = {'expand': 'body.storage,space,version'}
        url = base_url.rstrip('/') + '/rest/api/content'
        if uid:
            if not re.fullmatch(r'[0-9]+', uid):
                raise ValueError('invalid_content_id')
            url += '/' + uid
        else:
            params.update(spaceKey=space, title=title, type='page', limit=2)
        response = session.get(url, params=params)
        response.raise_for_status()
        payload = read_json(response)
        if uid:
            return payload
        results = payload.get('results') or []
        return results[0] if len(results) == 1 else None
    return ExcerptResolver(fetch, on_warning)
