from django import template

register = template.Library()


@register.simple_tag
def paginas_resultado(page):
    return page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
