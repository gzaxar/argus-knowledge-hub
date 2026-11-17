"""Preserve complex Confluence tables using a small HTML/formatting allowlist.

Simple tables remain Markdown. No source CSS, event handlers or active content
is emitted. Colour/width/alignment values become validated class tokens.
"""
from dataclasses import dataclass, field
from html import escape, unescape
from html.parser import HTMLParser
import re
from urllib.parse import quote, urlsplit
import uuid

_VOID = {'br', 'hr', 'img', 'col', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track'}
_ALLOWED = {'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'caption', 'colgroup', 'col',
            'p', 'br', 'hr', 'div', 'span', 'mark', 'strong', 'b', 'em', 'i', 'u', 's', 'del',
            'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'a', 'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
_DROP = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'form', 'input', 'button', 'textarea'}
_NAMED = {'white':'ffffff', 'black':'000000', 'red':'ff0000', 'green':'008000', 'blue':'0000ff',
          'yellow':'ffff00', 'gray':'808080', 'grey':'808080'}
_HIGHLIGHTS = {'grey':'f4f5f7', 'red':'ffebe6', 'yellow':'fffae6', 'green':'e3fcef',
               'blue':'deebff', 'purple':'eae6ff'}


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def _walk(node):
    yield node
    for child in node.children:
        if isinstance(child, Node):
            yield from _walk(child)


def _plain(node):
    return ''.join(_plain(child) if isinstance(child, Node) else child for child in node.children)


def _colour(value):
    value = (value or '').strip().lower()
    if re.fullmatch(r'#[0-9a-f]{6}', value):
        return value[1:]
    if re.fullmatch(r'#[0-9a-f]{3}', value):
        return ''.join(c*2 for c in value[1:])
    match = re.fullmatch(r'rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*1(?:\.0+)?)?\s*\)', value)
    if match and all(int(c) <= 255 for c in match.groups()):
        return ''.join(f'{int(c):02x}' for c in match.groups())
    return _NAMED.get(value)


def _properties(node):
    props = {}
    for part in (node.attrs.get('style') or '').split(';'):
        key, separator, value = part.partition(':')
        if separator:
            props[key.strip().lower()] = value.strip().lower()
    return props


def _format_classes(node):
    props = _properties(node)
    classes = []
    background = _colour(props.get('background-color') or node.attrs.get('data-highlight-colour')
                         or node.attrs.get('data-highlight-color') or node.attrs.get('bgcolor'))
    if not background:
        for token in (node.attrs.get('class') or '').split():
            match = re.fullmatch(r'highlight-(grey|red|yellow|green|blue|purple)', token)
            if match:
                background = _HIGHLIGHTS[match[1]]
    foreground = _colour(props.get('color') or node.attrs.get('color'))
    for key, value in [('bg', background), ('fg', foreground)]:
        if value:
            classes.append(f'argus-rich-{key}-{value}')
    width = props.get('width') or node.attrs.get('width') or node.attrs.get('data-table-width')
    match = re.fullmatch(r'(\d+(?:\.\d{1,3})?)(px|%)?', width or '')
    if match:
        value, unit = float(match[1]), match[2] or 'px'
        if 0 < value <= (100 if unit == '%' else 4096):
            number = format(value, 'g').replace('.', '_')
            classes.append(f'argus-rich-w-{number}{"pct" if unit == "%" else "px"}')
    align = props.get('text-align') or node.attrs.get('align')
    if align in {'left', 'center', 'right', 'justify'}:
        classes.append('argus-rich-align-'+align)
    valign = props.get('vertical-align') or node.attrs.get('valign')
    if valign in {'top', 'middle', 'bottom'}:
        classes.append('argus-rich-valign-'+valign)
    if props.get('font-weight') in {'bold', '700'}:
        classes.append('argus-rich-bold')
    if props.get('font-style') == 'italic':
        classes.append('argus-rich-italic')
    if props.get('text-decoration') == 'underline':
        classes.append('argus-rich-underline')
    if props.get('table-layout') == 'fixed':
        classes.append('argus-rich-fixed')
    return classes


def _complex(node):
    tables = 0
    for item in _walk(node):
        tables += item.tag == 'table'
        if tables > 1 or _format_classes(item):
            return True
        for attribute in ('colspan', 'rowspan'):
            value = item.attrs.get(attribute) or ''
            if value.isdigit() and 1 < int(value) <= 1000:
                return True
        if any(isinstance(c, str) and re.search(r'ARGUSPANEL[0-9a-f]{32}(?:OPEN|CLOSE)', c) for c in item.children):
            return True
    return False


def _url(value, image=False):
    value = (value or '').strip()
    if not value or re.search(r'[\x00-\x20\x7f\\]', value):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme.lower() in ({'http', 'https'} if image else {'http', 'https', 'mailto'}):
        return value
    if not parsed.scheme and not value.startswith('//'):
        return value
    return None


def _strip_status_prompt(node):
    if node.tag != 'tr':
        return
    cells = [c for c in node.children if isinstance(c, Node) and c.tag in {'td', 'th'}]
    if len(cells) != 2 or _plain(cells[0]).strip().lower() != 'document status':
        return
    match = re.match(r'^\s*SET\s+A\s+STATUS(?:\s+|$)', _plain(cells[1]), re.I)
    if not match or not _plain(cells[1])[match.end():].strip():
        return
    remaining = match.end()
    def remove_prefix(item):
        nonlocal remaining
        for index, child in enumerate(item.children):
            if not remaining:
                break
            if isinstance(child, Node):
                remove_prefix(child)
            else:
                count = min(remaining, len(child))
                item.children[index] = child[count:]
                remaining -= count
    remove_prefix(cells[1])


def _render(node, panels, inline_slots, table_depth=0):
    if isinstance(node, str):
        if node.strip() in inline_slots:
            return inline_slots[node.strip()]
        return escape(node, quote=False).replace('\n', '&#10;').replace('\r', '')
    if node.tag in _DROP:
        return ''
    text = _plain(node).strip()
    if node.tag == 'p' and text in panels:
        # Markers are generated by the existing panel converter, not source CSS.
        return panels[text]
    if node.tag == 'p' and text in inline_slots:
        return inline_slots[text]
    _strip_status_prompt(node)
    attrs = []
    classes = ['argus-confluence-rich-node'] + _format_classes(node)
    if node.tag == 'table':
        classes.append('argus-confluence-rich-table')
        if table_depth:
            classes.append('argus-confluence-nested-table')
    # Keep only the existing validated panel class tokens.
    for token in (node.attrs.get('class') or '').split():
        if re.fullmatch(r'argus-confluence-panel(?:-(?:bg|border)-[0-9a-f]{6})?', token):
            classes.append(token)
    attrs.append('class="'+' '.join(classes)+'"')
    if node.tag in {'td', 'th', 'col', 'colgroup'}:
        for attribute in (('colspan', 'rowspan') if node.tag in {'td', 'th'} else ('span',)):
            value = node.attrs.get(attribute) or ''
            if value.isdigit() and 1 <= int(value) <= 1000:
                attrs.append(f'{attribute}="{int(value)}"')
    if node.tag in {'a', 'img'}:
        key = 'src' if node.tag == 'img' else 'href'
        url = _url(node.attrs.get(key), image=node.tag == 'img')
        if url:
            attrs.append(f'{key}="{escape(url, quote=True)}"')
        if node.tag == 'img':
            attrs.append(f'alt="{escape(node.attrs.get("alt") or "", quote=True)}"')
    next_depth = table_depth + (node.tag == 'table')
    content = ''.join(_render(child, panels, inline_slots, next_depth) for child in node.children)
    if node.tag not in _ALLOWED:
        return content
    tag = f'<{node.tag} {" ".join(attrs)}>'
    return tag if node.tag in _VOID else tag+content+f'</{node.tag}>'


class _TableSpans(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.offsets = [0]
        for match in re.finditer('\n', source):
            self.offsets.append(match.end())
        self.depth = 0
        self.start = 0
        self.spans = []
        self.blocked = []

    def _offset(self):
        line, column = self.getpos()
        return self.offsets[line-1]+column

    def handle_starttag(self, tag, attrs):
        if tag in {'pre', 'code', 'script', 'style'}:
            self.blocked.append(tag)
        if not self.blocked and tag == 'table':
            if not self.depth:
                self.start = self._offset()
            self.depth += 1

    def handle_endtag(self, tag):
        if not self.blocked and tag == 'table' and self.depth:
            self.depth -= 1
            if not self.depth:
                self.spans.append((self.start, self.source.index('>', self._offset())+1))
        if self.blocked and tag == self.blocked[-1]:
            self.blocked.pop()


def protect_complex_tables(html, panels=None, inline_slots=None):
    """Replace complete outer complex tables with opaque markers before markdownify."""
    parser = _TableSpans(html)
    parser.feed(html)
    slots = {}
    for start, end in reversed(parser.spans):
        tree = _Tree()
        tree.feed(html[start:end])
        table = next((n for n in tree.root.children if isinstance(n, Node) and n.tag == 'table'), None)
        if table is None or not _complex(table):
            continue
        marker = 'ARGUSRICHTABLE'+uuid.uuid4().hex+'END'
        slots[marker] = _render(table, panels or {}, inline_slots or {})
        html = html[:start]+'<p>'+marker+'</p>'+html[end:]
    return html, slots


def restore_complex_tables(markdown, slots):
    # Restore after markdownify's HTML entity unescape so literal '<script>' text
    # remains escaped. Blank lines delimit CommonMark HTML blocks.
    for marker, table in slots.items():
        markdown = markdown.replace(marker, '\n\n'+table+'\n\n')
    return markdown


def table_contents_slots(html, slots, headings, title=None):
    """HTML contents lists for macros inside preserved tables; match normal TOC IDs."""
    if not slots:
        return {}
    from app.services.confluence_contents import heading_slug
    tree = _Tree()
    tree.feed(html)
    first = next((child for child in tree.root.children
                  if (_plain(child) if isinstance(child, Node) else child).strip()), None)
    already_title = isinstance(first, Node) and first.tag == 'h1' and _plain(first).strip() == title
    counts = {heading_slug(title): 1} if title and not already_title else {}
    targets = []
    for level, label in headings:
        slug = heading_slug(label)
        count = counts.get(slug, 0)
        counts[slug] = count+1
        anchor = 'argus-heading-'+slug+(f'-{count}' if count else '')
        targets.append((level, label, anchor))
    result = {}
    for marker, options in slots.items():
        roots, stack = [], []
        for level, label, anchor in targets:
            if not options.get('minLevel', 1) <= level <= options.get('maxLevel', 6):
                continue
            item = [label, anchor, []]
            while stack and stack[-1][0] >= level:
                stack.pop()
            (stack[-1][1][2] if stack else roots).append(item)
            stack.append((level, item))
        def render(items):
            if not items:
                return ''
            return '<ul>'+''.join('<li><a href="#'+quote(anchor, safe='-_')+'">'
                   +escape(re.sub(r'\s+', ' ', label).strip())+'</a>'+render(children)+'</li>'
                   for label, anchor, children in items)+'</ul>'
        result[marker] = render(roots)
    return result


def source_note_panel(body, block, slots):
    """A legacy Confluence Note: yellow panel, optional title, warning icon.

    Do not invent a 'Note' heading when the source supplied only body text.
    Delegate wrapper/token generation to the existing validated panel helper.
    """
    from app.services.confluence_visuals import panel_placeholder
    tree = _Tree()
    tree.feed(block)
    params = {node.attrs.get('ac:name'): _plain(node).strip()
              for node in _walk(tree.root) if node.tag == 'ac:parameter'}
    title = params.get('title', '')
    show_icon = params.get('icon', 'true').lower() != 'false'
    if not (body or '').strip() and not title:
        return ''
    if not params.get('bgColor') and not params.get('panelBGColor'):
        block = '<ac:parameter ac:name="bgColor">#fffae6</ac:parameter>'+block
    if show_icon:
        if title:
            block = '<ac:parameter ac:name="title">'+escape('⚠️ '+title)+'</ac:parameter>'+block
        else:
            # Keep the source's paragraphs and inline emphasis intact.
            body, count = re.subn(r'(<p\b[^>]*>)', r'\1⚠️ ', body, count=1, flags=re.I)
            if not count:
                body = '<p>⚠️</p>'+body
    return panel_placeholder('panel', body, block, slots)
