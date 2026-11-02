"""URLs de CSS/JS/imagens mudam quando o arquivo muda, evitando cache antigo."""
from pathlib import Path

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def recurso(nome):
    url = static(nome)
    caminho = finders.find(nome)
    if not caminho and settings.STATIC_ROOT:
        caminho = Path(settings.STATIC_ROOT) / nome
    try:
        versao = Path(caminho).stat().st_mtime_ns if caminho else None
    except OSError:
        versao = None
    return f"{url}{'&' if '?' in url else '?'}v={versao}" if versao is not None else url
