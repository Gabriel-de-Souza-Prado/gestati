from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from cadastros.forms import SituacaoCadastroForm
from cadastros.models import Fornecedor
from core.normalizacao import normalizar_identificador

from .forms import ComponenteForm, EntradaEstoqueForm, FiltroComponenteForm, FiltroMovimentoForm
from .models import Componente
from .selectors import componentes_com_saldo
from .services import definir_situacao_componente, excluir_componente, registrar_entrada, salvar_componente


def _adicionar_erros(form, erro):
    if hasattr(erro, "message_dict"):
        for campo, erros in erro.message_dict.items():
            form.add_error(campo if campo in form.fields else None, erros)
    else:
        form.add_error(None, erro)


def _filtros_url(request):
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return parametros.urlencode()


@login_required
@require_http_methods(["GET"])
def componente_listar(request):
    filtro = FiltroComponenteForm(request.GET)
    componentes = componentes_com_saldo().filter(acompanhar_estoque=True)
    if filtro.is_valid():
        dados = filtro.cleaned_data
        if dados["q"]:
            componentes = componentes.filter(chave_nome__contains=normalizar_identificador(dados["q"]))
        if dados["tipo"]:
            componentes = componentes.filter(tipo=dados["tipo"])
        if dados["situacao"]:
            componentes = componentes.filter(ativo=dados["situacao"] == "ativos")
        if dados["estoque"] == "baixo":
            componentes = componentes.filter(estoque_baixo=True)
        elif dados["estoque"] == "disponivel":
            componentes = componentes.filter(saldo__gt=0)
    else:
        componentes = componentes.none()
    pagina = Paginator(componentes, 15).get_page(request.GET.get("page"))
    return render(request, "estoque/componente_lista.html", {"filtro": filtro, "page_obj": pagina, "filtros_url": _filtros_url(request)})


def _formulario_componente(request, componente=None):
    campos = ("nome", "tipo", "descricao", "capacidade", "unidade_capacidade", "quantidade_minima")
    form = ComponenteForm(request.POST if request.method == "POST" else None, initial={campo: getattr(componente, campo) for campo in campos} if componente else None)
    if request.method == "POST" and form.is_valid():
        try:
            salvo = salvar_componente(**form.cleaned_data, componente_id=componente.pk if componente else None, acompanhar_estoque=None if componente else True)
        except ValidationError as erro:
            _adicionar_erros(form, erro)
        except Componente.DoesNotExist:
            raise Http404("Componente não encontrado.") from None
        else:
            messages.success(request, "Componente atualizado." if componente else "Componente cadastrado. Registre uma entrada quando houver peças disponíveis no estoque.")
            return redirect("estoque:componente_detalhar", pk=salvo.pk)
    return render(request, "estoque/componente_form.html", {"form": form, "componente": componente})


@login_required
@require_http_methods(["GET", "POST"])
def componente_criar(request):
    return _formulario_componente(request)


@login_required
@require_http_methods(["GET", "POST"])
def componente_editar(request, pk):
    return _formulario_componente(request, get_object_or_404(Componente, pk=pk))


@login_required
@require_http_methods(["GET"])
def componente_detalhar(request, pk):
    componente = get_object_or_404(componentes_com_saldo(), pk=pk)
    filtro = FiltroMovimentoForm(request.GET)
    movimentos = componente.movimentos.select_related("intervencao__registro_os", "intervencao__revisao_os__registro")
    if filtro.is_valid():
        dados = filtro.cleaned_data
        if dados["inicio"]:
            movimentos = movimentos.filter(data__gte=dados["inicio"])
        if dados["fim"]:
            movimentos = movimentos.filter(data__lte=dados["fim"])
        if dados["origem"]:
            movimentos = movimentos.filter(origem=dados["origem"])
    else:
        movimentos = movimentos.none()
    return render(request, "estoque/componente_detalhe.html", {
        "componente": componente, "filtro": filtro,
        "page_obj": Paginator(movimentos, 15).get_page(request.GET.get("page")),
        "filtros_url": _filtros_url(request),
    })


@login_required
@require_POST
def componente_situacao(request, pk):
    form = SituacaoCadastroForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Situação inválida.")
    try:
        definir_situacao_componente(componente_id=pk, ativo=form.cleaned_data["ativo"])
    except Componente.DoesNotExist:
        raise Http404("Componente não encontrado.") from None
    messages.success(request, "Componente ativado." if form.cleaned_data["ativo"] else "Componente inativado. O saldo e o histórico foram preservados.")
    return redirect("estoque:componente_detalhar", pk=pk)


@login_required
@require_http_methods(["GET", "POST"])
def componente_excluir(request, pk):
    componente = get_object_or_404(Componente, pk=pk)
    if request.method == "POST":
        try:
            excluir_componente(componente_id=pk)
        except ValidationError as erro:
            for mensagem in erro.messages:
                messages.error(request, mensagem)
            return redirect("estoque:componente_detalhar", pk=pk)
        except Componente.DoesNotExist:
            raise Http404("Componente não encontrado.") from None
        messages.success(request, "Componente excluído.")
        return redirect("estoque:componente_listar")
    return render(request, "estoque/componente_confirmar_exclusao.html", {"componente": componente})


@login_required
@require_http_methods(["GET", "POST"])
def entrada_criar(request):
    initial = {"componente": request.GET.get("componente")} if request.method == "GET" else None
    form = EntradaEstoqueForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        dados = form.cleaned_data
        try:
            movimento, criado = registrar_entrada(
                componente_id=dados["componente"].pk, quantidade=dados["quantidade"],
                origem=dados["origem"], data=dados["data"], usuario=request.user,
                fornecedor_id=dados["fornecedor"].pk if dados["fornecedor"] else None,
                observacao=dados["observacao"], chave_confirmacao=dados["chave_confirmacao"],
            )
        except ValidationError as erro:
            _adicionar_erros(form, erro)
        except (Componente.DoesNotExist, Fornecedor.DoesNotExist):
            form.add_error(None, "O cadastro selecionado mudou. Confira os dados antes de confirmar.")
        else:
            messages.success(request, "Entrada registrada." if criado else "Esta entrada já foi registrada. O estoque não foi acrescido novamente.")
            return redirect("estoque:componente_detalhar", pk=movimento.componente_id)
    return render(request, "estoque/entrada_form.html", {"form": form, "tem_componentes": Componente.objects.filter(ativo=True).exists()})
