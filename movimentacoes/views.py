from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from ativos.forms import FiltroAtivoForm
from ativos.selectors import ativos_para_consulta, filtrar_busca_ativos
from .forms import DevolucaoForm, EmprestimoForm, FiltroMovimentacaoForm, MovimentacaoForm
from .models import EmprestimoAtivo, TransferenciaAtivo
from .selectors import filtrar_movimentacoes
from .services import devolver_emprestimo, emprestar_ativo, transferir_ativo


TIPOS = {"transferencias": TransferenciaAtivo, "emprestimos": EmprestimoAtivo}


def _erros(form, erro):
    if hasattr(erro, "message_dict"):
        for campo, mensagens in erro.message_dict.items():
            form.add_error(campo if campo in form.fields else None, mensagens)
    else:
        form.add_error(None, erro)


@login_required
@require_http_methods(["GET"])
def listar(request):
    tipo = request.GET.get("tipo", "transferencias")
    if tipo not in TIPOS:
        raise Http404("Tipo de movimentação não encontrado.")
    filtro = FiltroMovimentacaoForm(request.GET, emprestimos=tipo == "emprestimos")
    consulta = TIPOS[tipo].objects.select_related("ativo")
    consulta = filtrar_movimentacoes(consulta, filtro.cleaned_data) if filtro.is_valid() else consulta.none()
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "movimentacoes/lista.html", {"tipo": tipo, "filtro": filtro, "page_obj": Paginator(consulta, 15).get_page(request.GET.get("page")), "filtros_url": parametros.urlencode()})


@login_required
@require_http_methods(["GET"])
def selecionar(request, tipo):
    if tipo not in TIPOS:
        raise Http404("Tipo de movimentação não encontrado.")
    filtro = FiltroAtivoForm(request.GET)
    consulta = ativos_para_consulta().none()
    if filtro.is_valid() and filtro.cleaned_data.get("q"):
        d = filtro.cleaned_data
        consulta = filtrar_busca_ativos(ativos_para_consulta(), d["q"])
        for campo in ("categoria", "departamento", "situacao"):
            if d[campo]:
                consulta = consulta.filter(**{campo: d[campo]})
    return render(request, "movimentacoes/selecionar.html", {"tipo": tipo, "filtro": filtro, "ativos": consulta[:50]})


@login_required
@require_http_methods(["GET", "POST"])
def registrar(request, tipo, ativo_pk):
    if tipo not in TIPOS:
        raise Http404("Tipo de movimentação não encontrado.")
    ativo = get_object_or_404(ativos_para_consulta(), pk=ativo_pk)
    classe = EmprestimoForm if tipo == "emprestimos" else MovimentacaoForm
    emprestimo_atual = next(iter(ativo.emprestimos_em_aberto), None)
    initial = {"versao": ativo.versao}
    if tipo == "transferencias" and emprestimo_atual:
        initial["destino"] = emprestimo_atual.destino_id
    form = classe(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        dados = dict(form.cleaned_data)
        dados["destino_id"] = dados.pop("destino").pk
        try:
            servico = emprestar_ativo if tipo == "emprestimos" else transferir_ativo
            registro, criado = servico(ativo_id=ativo.pk, usuario=request.user, **dados)
        except ValidationError as erro:
            _erros(form, erro)
        else:
            messages.success(request, "Movimentação registrada." if criado else "Esta movimentação já foi confirmada anteriormente.")
            return redirect("movimentacoes:detalhar", tipo=tipo, pk=registro.pk)
    return render(request, "movimentacoes/form.html", {"tipo": tipo, "ativo": ativo, "form": form, "emprestimo_atual": emprestimo_atual})


@login_required
@require_http_methods(["GET"])
def detalhar(request, tipo, pk):
    if tipo not in TIPOS:
        raise Http404("Tipo de movimentação não encontrado.")
    registro = get_object_or_404(TIPOS[tipo].objects.select_related("ativo"), pk=pk)
    return render(request, "movimentacoes/detalhe.html", {"tipo": tipo, "registro": registro})


@login_required
@require_http_methods(["GET", "POST"])
def devolver(request, pk):
    emprestimo = get_object_or_404(EmprestimoAtivo.objects.select_related("ativo"), pk=pk)
    form = DevolucaoForm(request.POST if request.method == "POST" else None, initial={"versao": emprestimo.ativo.versao})
    if request.method == "POST" and form.is_valid():
        try:
            registro, criado = devolver_emprestimo(emprestimo_id=emprestimo.pk, usuario=request.user, **form.cleaned_data)
        except ValidationError as erro:
            _erros(form, erro)
        else:
            messages.success(request, "Devolução registrada. O empréstimo foi encerrado." if criado else "Esta devolução já foi confirmada anteriormente.")
            return redirect("movimentacoes:detalhar", tipo="emprestimos", pk=registro.pk)
    return render(request, "movimentacoes/devolver.html", {"emprestimo": emprestimo, "form": form})


@login_required
@require_http_methods(["GET"])
@never_cache
def imprimir_transferencia(request, pk):
    from .pdf import gerar_pdf_transferencia

    with transaction.atomic():
        registro = get_object_or_404(TransferenciaAtivo.objects.select_for_update(), pk=pk)
        conteudo = gerar_pdf_transferencia(registro)
    resposta = HttpResponse(conteudo, content_type="application/pdf")
    resposta["Content-Disposition"] = f'inline; filename="GESTATI-Transferencia-{registro.pk}.pdf"'
    return resposta
