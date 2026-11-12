"""Safe source emoji and panel wrappers. Formatting only; no remote resources fetched."""
import re
import uuid
import unicodedata
from html import escape, unescape
from html.parser import HTMLParser


class _Attributes(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.attrs = {}

    def handle_starttag(self, tag, attrs):
        self.attrs = dict(attrs)


_EMOJI = {
    'blue_book': '📘', 'books': '📚', 'book': '📖', 'clipboard': '📋', 'compass': '🧭',
    'information': 'ℹ️', 'information_source': 'ℹ️', 'warning': '⚠️', 'tick': '✅',
    'cross': '❌', 'thumbs_up': '👍', 'thumbs_down': '👎', 'smile': '🙂',
    'sad': '🙁', 'wink': '😉', 'laugh': '😄', 'cheeky': '😛', 'yellow_star': '⭐',
}
_OPAQUE = re.compile(r'<(ac:plain-text-body|pre|code)\b[^>]*>.*?</\1\s*>|<!--.*?-->', re.I | re.S)
_EMOTICON = re.compile(r'<ac:emoticon\b[^>]*?(?:/\s*>|>\s*</ac:emoticon\s*>)', re.I | re.S)


def _emoji(match):
    parser = _Attributes()
    parser.feed(match.group(0))
    attrs = parser.attrs
    fallback = attrs.get('ac:emoji-fallback', '')
    if (fallback and len(fallback) <= 64
            and any(ord(c) >= 0x1f000 or 0x2600 <= ord(c) <= 0x27bf for c in fallback)
            and not any(unicodedata.category(c).startswith('L') or c in '<>&\r\n' for c in fallback)):
        return escape(fallback)
    identifier = attrs.get('ac:emoji-id', '')
    if re.fullmatch(r'[\da-fA-F]{2,6}(?:[-_][\da-fA-F]{2,6})*', identifier):
        values = [int(part, 16) for part in re.split('[-_]', identifier)]
        if (all(0 <= value <= 0x10ffff and not 0xd800 <= value <= 0xdfff for value in values)
                and any(value >= 0x1f000 or 0x2600 <= value <= 0x27bf for value in values)):
            return escape(''.join(chr(value) for value in values))
    name = attrs.get('ac:emoji-shortname') or attrs.get('ac:name') or ''
    name = name.strip(':').lower().replace('-', '_')
    return _EMOJI.get(name, '[Confluence icon unavailable]')


def render_emoticons(storage: str) -> str:
    out = []
    offset = 0
    for match in _OPAQUE.finditer(storage):
        out.extend((_EMOTICON.sub(_emoji, storage[offset:match.start()]), match.group(0)))
        offset = match.end()
    out.append(_EMOTICON.sub(_emoji, storage[offset:]))
    return ''.join(out)


def _parameter(block: str, name: str) -> str:
    match = re.search(r'<ac:parameter\b[^>]*ac:name=["\']' + re.escape(name)
                      + r'["\'][^>]*>(.*?)</ac:parameter>', block, re.I | re.S)
    if not match:
        return ''
    return unescape(re.sub('<[^>]+>', '', match.group(1))).strip()


def _colour(value: str) -> str | None:
    if re.fullmatch(r'#[\da-fA-F]{6}', value):
        return value[1:].lower()
    if re.fullmatch(r'#[\da-fA-F]{3}', value):
        return ''.join(c * 2 for c in value[1:].lower())
    return {'white': 'ffffff', 'black': '000000', 'yellow': 'ffff00',
            'blue': '0000ff', 'red': 'ff0000', 'green': '008000'}.get(value.lower())


_DEFAULTS = {'info': ('ℹ️', 'deebff'), 'note': ('📝', 'eae6ff'),
             'warning': ('⚠️', 'fffae6'), 'tip': ('💡', 'e3fcef'), 'caution': ('⚠️', 'fffae6')}


def panel_placeholder(name: str, body: str, block: str, slots: dict) -> str:
    icon, default_bg = _DEFAULTS.get(name, ('', 'f4f5f7'))
    background = _colour(_parameter(block, 'bgColor') or _parameter(block, 'panelBGColor')) or default_bg
    border = _colour(_parameter(block, 'borderColor'))
    title = _parameter(block, 'title')
    if not title and name in _DEFAULTS:
        title = name.title()
    if not body.strip() and not title:
        return ''
    marker = 'ARGUSPANEL' + uuid.uuid4().hex
    classes = 'argus-confluence-panel argus-confluence-panel-bg-' + background
    if border:
        classes += ' argus-confluence-panel-border-' + border
    slots[marker + 'OPEN'] = f'<div class="{classes}">'
    slots[marker + 'CLOSE'] = '</div>'
    header = f'<p><strong>{icon + " " if icon else ""}{escape(title)}</strong></p>' if title else ''
    return f'<p>{marker}OPEN</p>{header}{body}<p>{marker}CLOSE</p>'


def render_panel_wrappers(markdown: str, slots: dict) -> str:
    for marker, wrapper in slots.items():
        # Blank lines let Markdown paragraphs/lists inside the raw HTML wrapper
        # remain Markdown nodes when remark/rehype render the document.
        lines = []
        for line in markdown.split('\n'):
            if marker in line and line.lstrip().startswith('|'):
                # Do not break a Markdown table with raw block HTML. Content is
                # retained there; panel background styling is an outside-table feature.
                lines.append(line.replace(marker, ''))
            else:
                lines.append(line.replace(marker, '\n' + wrapper + '\n'))
        markdown = '\n'.join(lines)
    return markdown
