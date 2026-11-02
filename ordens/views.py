from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from ativos.composicao import calcular_ram_total_gb
from ativos.forms import FiltroAtivoForm
from ativos.selectors import ativos_para_consulta, filtrar_busca_ativos
from . import forms, services
from .models import OrdemServico as OS
from .selectors import filtrar_ordens, ordens_para_consulta, registros_para_apresentacao


def _erros(form, erro):
    if hasattr(erro, "message_dict"):
        for campo, mensagens in erro.message_dict.items():
            form.add_error(campo if campo in form.fields else None, mensagens)
    else:
        form.add_error(None, erro)


@login_required
@require_http_methods(["GET"])
def listar(request):
    filtro = forms.FiltroOSForm(request.GET)
    consulta = filtrar_ordens(ordens_para_consulta(), filtro.cleaned_data) if filtro.is_valid() else OS.objects.none()
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "ordens/lista.html", {"filtro": filtro, "page_obj": Paginator(consulta, 15).get_page(request.GET.get("page")), "filtros_url": parametros.urlencode()})


@login_required
@require_http_methods(["GET"])
def selecionar_ativo(request):
    filtro = FiltroAtivoForm(request.GET)
    ativos = ativos_para_consulta().none()
    if filtro.is_valid() and filtro.cleaned_data.get("q"):
        ativos = filtrar_busca_ativos(ativos_para_consulta(), filtro.cleaned_data["q"])
        for campo in ("categoria", "departamento", "situacao"):
            if filtro.cleaned_data[campo]:
                ativos = ativos.filter(**{campo: filtro.cleaned_data[campo]})
    return render(request, "ordens/selecionar.html", {"filtro": filtro, "ativos": ativos[:50]})


@login_required
@require_http_methods(["GET", "POST"])
def abrir(request, ativo_pk):
    ativo = get_object_or_404(ativos_para_consulta(), pk=ativo_pk)
    existente = ativo.ordens_servico.exclude(status=OS.Status.ENCERRADA).first()
    form = forms.AberturaForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            ordem, criada = services.abrir_os(ativo_id=ativo.pk, usuario=request.user, **form.cleaned_data)
        except ValidationError as erro:
            _erros(form, erro)
        else:
            messages.success(request, "OS aberta. O departamento do ativo foi preservado." if criada else "Esta OS já foi aberta anteriormente.")
            return redirect("ordens:detalhar", pk=ordem.pk)
    return render(request, "ordens/abrir.html", {"form": form, "ativo": ativo, "existente": existente, "em_garantia": ativo.esta_em_garantia()})


@login_required
@require_http_methods(["GET"])
def detalhar(request, pk):
    ordem = get_object_or_404(ordens_para_consulta(), pk=pk)
    instalados = list(ordem.ativo.componentes_instalados.select_related("componente"))
    return render(request, "ordens/detalhe.html", {
        "ordem": ordem, "registros": registros_para_apresentacao(ordem), "instalados": instalados,
        "ram_total": calcular_ram_total_gb([(l.componente, l.quantidade) for l in instalados]),
        "em_trabalho": ordem.status in services.ESTADOS_TRABALHO,
        "aguardando_coleta": ordem.status == OS.Status.AGUARDANDO_COLETA,
    })


OPERACOES = {
    "andamento": (forms.AndamentoForm, "Atualizar andamento", "Salvar andamento"),
    "servico": (forms.ServicoForm, "Registrar serviço", "Confirmar serviço e peças"),
    "concluir": (forms.ConclusaoForm, "Concluir trabalho técnico", "Concluir e aguardar coleta"),
    "devolver": (forms.EncerramentoForm, "Registrar devolução", "Devolver e encerrar OS"),
    "para-baixa": (forms.BaixaForm, "Encerrar OS para baixa", "Encerrar para baixa"),
}


@login_required
@require_http_methods(["GET", "POST"])
def operar(request, pk, acao):
    if acao not in OPERACOES:
        raise Http404("Operação não encontrada.")
    ordem = get_object_or_404(ordens_para_consulta(), pk=pk)
    classe, titulo, botao = OPERACOES[acao]
    post = request.POST if request.method == "POST" else None
    form = classe(post, initial={"versao": ordem.versao})
    pecas = forms.PecasFormSet(post, prefix="pecas", form_kwargs={"ativo_id": ordem.ativo_id}) if acao == "servico" else None
    if post is not None:
        valido = form.is_valid()
        pecas_validas = pecas.is_valid() if pecas is not None else True
        if valido and pecas_validas:
            dados = {"ordem_id": ordem.pk, "usuario": request.user, **form.cleaned_data}
            try:
                if acao == "andamento":
                    registro, criado = services.atualizar_andamento(**dados)
                elif acao == "servico":
                    itens = [{"componente_id": l["componente"].pk, "acao": l["acao"], "quantidade": l["quantidade"]} for l in pecas.cleaned_data if l and not l.get("DELETE")]
                    registro, criado = services.registrar_servico(**dados, itens=itens)
                elif acao == "concluir":
                    registro, criado = services.concluir_os(**dados)
                else:
                    registro, criado = services.encerrar_os(**dados, para_baixa=acao == "para-baixa", **({"recebido_por": ""} if acao == "para-baixa" else {}))
            except ValidationError as erro:
                _erros(form, erro)
            else:
                messages.success(request, "Atendimento confirmado." if criado else "Esta operação já havia sido confirmada. As peças não foram movimentadas novamente.")
                return redirect("ordens:detalhar", pk=ordem.pk)
    instalados = list(ordem.ativo.componentes_instalados.select_related("componente")) if pecas is not None else []
    return render(request, "ordens/operacao.html", {"ordem": ordem, "form": form, "pecas": pecas, "acao": acao, "titulo": titulo, "botao": botao, "instalados": instalados})


@login_required
@require_http_methods(["GET"])
@never_cache
def imprimir(request, pk):
    from .pdf import gerar_pdf_os

    # Os serviços também bloqueiam a OS antes de gravar seus registros.
    # O PDF deve ler um conjunto consistente, mesmo durante uma confirmação.
    with transaction.atomic():
        ordem = get_object_or_404(OS.objects.select_for_update(), pk=pk)
        conteudo = gerar_pdf_os(ordem)
    resposta = HttpResponse(conteudo, content_type="application/pdf")
    resposta["Content-Disposition"] = f'inline; filename="GESTATI-OS-{ordem.pk}.pdf"'
    return resposta


@login_required
@require_http_methods(["GET", "POST"])
def servico_editar(request, pk, registro_pk):
    from django.core import signing
    from .edicao import editar_servico, itens_do_servico
    from .models import RegistroAtendimento, RevisaoServico

    ordem = get_object_or_404(ordens_para_consulta(), pk=pk)
    registro = get_object_or_404(RegistroAtendimento, pk=registro_pk, ordem=ordem, tipo="servico")
    post = request.POST if request.method == "POST" else None
    erro = None
    if post is not None and "confirmacao" in post:
        try:
            d = signing.loads(post["confirmacao"], salt="edicao-servico-os", max_age=1800)
            if d["usuario_id"] != request.user.pk or d["dados"]["ordem_id"] != ordem.pk or d["dados"]["registro_id"] != registro.pk:
                raise signing.BadSignature()
            revisao, criado = editar_servico(**d["dados"], usuario=request.user, previa=d["previa"])
        except (signing.BadSignature, KeyError, TypeError):
            erro = "A conferência expirou ou é inválida. Reabra a edição."
        except ValidationError as exc:
            erro = " ".join(exc.messages)
        else:
            messages.success(request, "Serviço editado, com configuração e estoque ajustados." if criado else "Esta edição já foi confirmada. As peças não foram movimentadas novamente.")
            return redirect("ordens:detalhar", pk=ordem.pk)
        post = None
    itens_atuais = itens_do_servico(registro)
    ultima = registro.revisoes.first()
    form = forms.EdicaoServicoForm(post, initial={"versao": ordem.versao, "descricao": ultima.descricao if ultima else registro.descricao})
    iniciais = [{"componente": i["componente_id"], "quantidade": i["quantidade"], "acao": i["acao"]} for i in itens_atuais]
    pecas = forms.PecasFormSet(post, prefix="pecas", initial=iniciais, form_kwargs={"ativo_id": ordem.ativo_id,
        "componentes_permitidos": [i["componente_id"] for i in itens_atuais]})
    if erro:
        form.cleaned_data = {}
        form.add_error(None, erro)
    if post is not None:
        valido, pecas_validas = form.is_valid(), pecas.is_valid()
        if valido and pecas_validas:
            d = form.cleaned_data
            dados = {"ordem_id": ordem.pk, "registro_id": registro.pk, "descricao": d["descricao"], "justificativa": d["justificativa"],
                "versao": d["versao"], "chave_confirmacao": str(d["chave_confirmacao"]),
                "itens": [{"componente_id": i["componente"].pk, "quantidade": i["quantidade"], "acao": i["acao"]} for i in pecas.cleaned_data if i and not i.get("DELETE")]}
            try:
                previa, _ = editar_servico(**dados, usuario=request.user)
            except ValidationError as exc:
                _erros(form, exc)
            else:
                if isinstance(previa, RevisaoServico):
                    return redirect("ordens:detalhar", pk=ordem.pk)
                token = signing.dumps({"dados": dados, "previa": previa, "usuario_id": request.user.pk}, salt="edicao-servico-os", compress=True)
                return render(request, "ordens/edicao_previa.html", {"ordem": ordem, "registro": registro, "previa": previa,
                    "descricao": d["descricao"], "justificativa": d["justificativa"], "token": token})
    return render(request, "ordens/edicao_form.html", {"ordem": ordem, "registro": registro, "form": form, "pecas": pecas,
        "instalados": ordem.ativo.componentes_instalados.select_related("componente")})
