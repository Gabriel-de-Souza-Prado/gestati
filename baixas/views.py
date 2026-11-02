from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from ativos.forms import FiltroAtivoForm
from ativos.selectors import ativos_para_consulta, filtrar_busca_ativos
from .forms import BaixaForm, FiltroBaixaForm
from .models import BaixaAtivo
from .selectors import baixas_para_consulta
from .services import baixar_ativo


@login_required
@require_http_methods(["GET"])
def listar(request):
    filtro = FiltroBaixaForm(request.GET)
    registros = baixas_para_consulta(filtro.cleaned_data) if filtro.is_valid() else BaixaAtivo.objects.none()
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "baixas/lista.html", {"filtro": filtro,
        "page_obj": Paginator(registros, 15).get_page(request.GET.get("page")), "filtros_url": parametros.urlencode()})


@login_required
@require_http_methods(["GET"])
def selecionar(request):
    filtro = FiltroAtivoForm(request.GET)
    ativos = ativos_para_consulta().none()
    if filtro.is_valid() and filtro.cleaned_data.get("q"):
        ativos = filtrar_busca_ativos(ativos_para_consulta(), filtro.cleaned_data["q"])
        for campo in ("categoria", "departamento", "situacao"):
            if filtro.cleaned_data[campo]:
                ativos = ativos.filter(**{campo: filtro.cleaned_data[campo]})
    return render(request, "baixas/selecionar.html", {"filtro": filtro, "ativos": ativos[:50]})


@login_required
@require_http_methods(["GET", "POST"])
def registrar(request, ativo_pk):
    ativo = get_object_or_404(ativos_para_consulta(), pk=ativo_pk)
    erro = None
    post = request.POST if request.method == "POST" else None
    # Reenvio é tratado pelo serviço antes de avaliar a nova situação Baixado.
    if post is not None and "confirmacao" in post:
        try:
            assinado = signing.loads(post["confirmacao"], salt="baixa-ativo", max_age=1800)
            if assinado["usuario_id"] != request.user.pk or assinado["dados"]["ativo_id"] != ativo.pk:
                raise signing.BadSignature()
            registro, criado = baixar_ativo(**assinado["dados"], usuario=request.user, previa=assinado["previa"])
        except (signing.BadSignature, KeyError, TypeError):
            erro = "A conferência expirou ou é inválida. Preencha novamente para revisar a baixa."
        except ValidationError as exc:
            erro = " ".join(exc.messages)
        else:
            mensagem = ("Baixa confirmada e peças selecionadas recebidas no estoque." if registro.recuperados
                        else "Baixa confirmada, sem recuperação de peças para o estoque.")
            messages.success(request, mensagem if criado else "Esta baixa já foi confirmada. Nenhuma peça foi recebida novamente.")
            return redirect("baixas:detalhar", pk=registro.pk)
        post = None
    existente = BaixaAtivo.objects.filter(ativo=ativo).first()
    if existente and erro is None:
        return redirect("baixas:detalhar", pk=existente.pk)
    ultima_os = ativo.ordens_servico.first()
    ordem = ultima_os if ultima_os and ultima_os.encerrada_para_baixa else None
    instalados = list(ativo.componentes_instalados.select_related("componente"))
    form = BaixaForm(post, instalados=instalados, initial={"versao": ativo.versao})
    if erro:
        form.cleaned_data = {}
        form.add_error(None, erro)
    if post is not None and form.is_valid():
        d = form.cleaned_data
        dados = {"ativo_id": ativo.pk, "motivo": d["motivo"], "itens": form.itens(), "versao": d["versao"],
                 "ordem_id": ordem.pk if ordem else None, "chave_confirmacao": str(d["chave_confirmacao"])}
        try:
            previa, _ = baixar_ativo(**dados, usuario=request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            if isinstance(previa, BaixaAtivo):
                return redirect("baixas:detalhar", pk=previa.pk)
            token = signing.dumps({"dados": dados, "previa": previa, "usuario_id": request.user.pk}, salt="baixa-ativo", compress=True)
            return render(request, "baixas/previa.html", {"ativo": ativo, "ordem": ordem, "motivo": d["motivo"], "previa": previa, "token": token})
    return render(request, "baixas/form.html", {"ativo": ativo, "ordem": ordem, "form": form,
        "os_aberta": ativo.ordens_servico.exclude(status="encerrada").first(),
        "emprestimo": next(iter(ativo.emprestimos_em_aberto), None)})


@login_required
@require_http_methods(["GET"])
def detalhar(request, pk):
    registro = get_object_or_404(BaixaAtivo.objects.select_related("ativo", "ordem"), pk=pk)
    return render(request, "baixas/detalhe.html", {"registro": registro})


@login_required
@require_http_methods(["GET"])
@never_cache
def imprimir(request, pk):
    from .pdf import gerar_pdf_baixa
    registro = get_object_or_404(BaixaAtivo, pk=pk)
    resposta = HttpResponse(gerar_pdf_baixa(registro), content_type="application/pdf")
    resposta["Content-Disposition"] = f'inline; filename="GESTATI-Baixa-{registro.pk}.pdf"'
    return resposta
