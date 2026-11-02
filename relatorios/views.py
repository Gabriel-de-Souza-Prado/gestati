from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .apresentacao import linha
from .definicoes import RELATORIOS
from .forms import descrever_filtros, formulario
from .selectors import consultar


@login_required
@require_http_methods(["GET"])
def inicio(request):
    return render(request, "relatorios/inicio.html", {"relatorios": RELATORIOS})


@login_required
@require_http_methods(["GET"])
@never_cache
def consultar_relatorio(request, tipo, pdf=False):
    if tipo not in RELATORIOS:
        raise Http404("Relatório não encontrado.")
    definicao = RELATORIOS[tipo]
    form = formulario(tipo, request.GET)
    valido = form.is_valid()
    filtros = descrever_filtros(form) if valido else []
    consulta = consultar(tipo, form.cleaned_data) if valido else None
    emitido_em = timezone.now()
    if pdf and valido:
        from .pdf import gerar_pdf_relatorio
        linhas = [linha(tipo, registro)["celulas"] for registro in consulta]
        resposta = HttpResponse(gerar_pdf_relatorio(definicao=definicao, linhas=linhas,
            filtros=filtros, emitido_em=emitido_em, emitido_por=request.user.get_full_name() or request.user.username),
            content_type="application/pdf")
        resposta["Content-Disposition"] = f'inline; filename="GESTATI-Relatorio-{tipo}-{timezone.localdate()}.pdf"'
        return resposta
    pagina = Paginator(consulta if consulta is not None else [], 15).get_page(request.GET.get("page"))
    linhas = []
    for registro in pagina:
        dados = linha(tipo, registro)
        args = [tipo, registro.pk] if tipo in ("transferencias", "emprestimos") else [registro.pk]
        dados["url"] = reverse(definicao.detalhe, args=args)
        linhas.append(dados)
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "relatorios/consulta.html", {
        "tipo": tipo, "definicao": definicao, "relatorios": RELATORIOS,
        "filtro": form, "filtros": filtros, "valido": valido, "page_obj": pagina,
        "linhas": linhas, "filtros_url": parametros.urlencode(), "emitido_em": emitido_em,
    }, status=400 if pdf and not valido else 200)
