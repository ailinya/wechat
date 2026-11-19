"""Markdown preview with raw HTML disabled and restricted link destinations."""
from html import escape
import re
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

from app.schemas.articles import LayoutConfig


def safe_url(url):
    if re.fullmatch(r'/api/v1/files/[0-9a-fA-F-]{36}/image', url):
        return True
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and bool(parsed.hostname) and not any(c in url for c in ('\n', '\r', '\x00'))


def preview(markdown, layout):
    config = LayoutConfig.model_validate(layout) if isinstance(layout, dict) else layout
    parser = MarkdownIt('commonmark', {'html': False, 'breaks': True})
    parser.validateLink = safe_url
    tokens = parser.parse(markdown)
    radius = 8 if config.image_style == 'rounded' else 0
    heading_color = {'classic': '#1e293b', 'news': '#1d4ed8', 'minimal': '#111827'}[config.template]
    def decorate(items):
        for token in items:
            if token.type == 'paragraph_open':
                token.attrSet('style', f'margin:0 0 {config.paragraph_spacing}px')
            elif token.type == 'heading_open':
                token.attrSet('style', f'color:{heading_color};line-height:1.4')
            elif token.type == 'image':
                token.attrSet('style', f'max-width:100%;height:auto;border-radius:{radius}px')
                token.attrSet('referrerpolicy', 'no-referrer')
            elif token.type == 'link_open':
                token.attrSet('rel', 'noopener noreferrer')
            if token.children:
                decorate(token.children)
    decorate(tokens)
    body = parser.renderer.render(tokens, parser.options, {})
    style = f'font-family:{config.font_family};font-size:{config.font_size}px;line-height:{config.line_height};overflow-wrap:anywhere'
    return f'<section style="{escape(style, quote=True)}">{body}</section>'
