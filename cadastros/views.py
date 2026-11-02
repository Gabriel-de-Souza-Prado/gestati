from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (
    DepartamentoForm, FiltroDepartamentoForm, SituacaoCadastroForm,
    FornecedorForm, FiltroFornecedorForm,
    CategoriaAtivoForm, FiltroCategoriaForm,
)
from .models import CategoriaAtivo, Departamento, Fornecedor, normalizar_identificador
from .services import (
    definir_situacao_departamento,
    excluir_departamento,
    salvar_departamento,
    definir_situacao_fornecedor,
    excluir_fornecedor,
    salvar_fornecedor,
    salvar_categoria,
    adicionar_categorias_iniciais,
    definir_situacao_categoria,
    excluir_categoria,
)


@login_required
@require_http_methods(["GET"])
def departamento_listar(request):
    filtro = FiltroDepartamentoForm(request.GET)
    departamentos = Departamento.objects.all()
    if filtro.is_valid():
        termo = normalizar_identificador(filtro.cleaned_data["q"])
        if termo:
            departamentos = departamentos.filter(
                Q(chave_nome__contains=termo)
                | Q(identificadores__chave__contains=termo)
            ).distinct()
        situacao = filtro.cleaned_data["situacao"]
        if situacao:
            departamentos = departamentos.filter(ativo=situacao == "ativos")
    else:
        departamentos = departamentos.none()
    pagina = Paginator(departamentos, 15).get_page(request.GET.get("page"))
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(
        request,
        "cadastros/departamento_lista.html",
        {"filtro": filtro, "page_obj": pagina, "filtros_url": parametros.urlencode()},
    )


def _adicionar_erros(form, erro):
    if hasattr(erro, "message_dict"):
        for campo, mensagens in erro.message_dict.items():
            form.add_error(campo if campo in form.fields else None, mensagens)
    else:
        form.add_error(None, erro)


def _formulario_departamento(request, departamento=None):
    form = DepartamentoForm(
        request.POST if request.method == "POST" else None,
        initial={"nome": departamento.nome, "sigla": departamento.sigla}
        if departamento
        else None,
    )
    if request.method == "POST" and form.is_valid():
        try:
            salvar_departamento(
                **form.cleaned_data,
                departamento_id=departamento.pk if departamento else None,
            )
        except ValidationError as erro:
            _adicionar_erros(form, erro)
        except Departamento.DoesNotExist:
            raise Http404("Departamento não encontrado.") from None
        else:
            messages.success(
                request, "Departamento atualizado." if departamento else "Departamento cadastrado."
            )
            return redirect("cadastros:departamento_listar")
    return render(
        request,
        "cadastros/departamento_form.html",
        {"form": form, "departamento": departamento},
    )


@login_required
@require_http_methods(["GET", "POST"])
def departamento_criar(request):
    return _formulario_departamento(request)


@login_required
@require_http_methods(["GET", "POST"])
def departamento_editar(request, pk):
    return _formulario_departamento(request, get_object_or_404(Departamento, pk=pk))


@login_required
@require_POST
def departamento_situacao(request, pk):
    form = SituacaoCadastroForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Situação inválida.")
    try:
        definir_situacao_departamento(departamento_id=pk, ativo=form.cleaned_data["ativo"])
    except Departamento.DoesNotExist:
        raise Http404("Departamento não encontrado.") from None
    messages.success(
        request,
        "Departamento ativado." if form.cleaned_data["ativo"] else "Departamento inativado.",
    )
    return redirect("cadastros:departamento_listar")


@login_required
@require_http_methods(["GET", "POST"])
def departamento_excluir(request, pk):
    departamento = get_object_or_404(Departamento, pk=pk)
    if request.method == "POST":
        try:
            excluir_departamento(departamento_id=pk)
        except ValidationError as erro:
            for mensagem in erro.messages:
                messages.error(request, mensagem)
        except Departamento.DoesNotExist:
            raise Http404("Departamento não encontrado.") from None
        else:
            messages.success(request, "Departamento excluído.")
        return redirect("cadastros:departamento_listar")
    return render(
        request, "cadastros/departamento_confirmar_exclusao.html", {"departamento": departamento}
    )


@login_required
@require_http_methods(["GET"])
def fornecedor_listar(request):
    filtro = FiltroFornecedorForm(request.GET)
    fornecedores = Fornecedor.objects.all()
    if filtro.is_valid():
        termo = normalizar_identificador(filtro.cleaned_data["q"])
        if termo:
            identificador = termo.replace(".", "").replace("/", "").replace("-", "").upper()
            busca = Q(chave_nome__contains=termo)
            if identificador:
                busca |= Q(cnpj__contains=identificador)
            fornecedores = fornecedores.filter(busca)
        situacao = filtro.cleaned_data["situacao"]
        if situacao:
            fornecedores = fornecedores.filter(ativo=situacao == "ativos")
    else:
        fornecedores = fornecedores.none()
    pagina = Paginator(fornecedores, 15).get_page(request.GET.get("page"))
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(
        request, "cadastros/fornecedor_lista.html",
        {"filtro": filtro, "page_obj": pagina, "filtros_url": parametros.urlencode()},
    )


def _formulario_fornecedor(request, fornecedor=None):
    form = FornecedorForm(
        request.POST if request.method == "POST" else None,
        initial={"nome": fornecedor.nome, "cnpj": fornecedor.cnpj_formatado,
                 "telefone": fornecedor.telefone, "email": fornecedor.email}
        if fornecedor else None,
    )
    if request.method == "POST" and form.is_valid():
        try:
            salvo = salvar_fornecedor(
                **form.cleaned_data, fornecedor_id=fornecedor.pk if fornecedor else None,
            )
        except ValidationError as erro:
            _adicionar_erros(form, erro)
        except Fornecedor.DoesNotExist:
            raise Http404("Fornecedor não encontrado.") from None
        else:
            messages.success(request, "Fornecedor atualizado." if fornecedor else "Fornecedor cadastrado.")
            if Fornecedor.objects.filter(chave_nome=salvo.chave_nome).exclude(pk=salvo.pk).exists():
                messages.warning(
                    request, "Há outro fornecedor com esse nome. Confira o CNPJ na lista para evitar cadastros duplicados."
                )
            return redirect("cadastros:fornecedor_listar")
    return render(
        request, "cadastros/fornecedor_form.html", {"form": form, "fornecedor": fornecedor},
    )


@login_required
@require_http_methods(["GET", "POST"])
def fornecedor_criar(request):
    return _formulario_fornecedor(request)


@login_required
@require_http_methods(["GET", "POST"])
def fornecedor_editar(request, pk):
    return _formulario_fornecedor(request, get_object_or_404(Fornecedor, pk=pk))


@login_required
@require_POST
def fornecedor_situacao(request, pk):
    form = SituacaoCadastroForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Situação inválida.")
    try:
        definir_situacao_fornecedor(fornecedor_id=pk, ativo=form.cleaned_data["ativo"])
    except Fornecedor.DoesNotExist:
        raise Http404("Fornecedor não encontrado.") from None
    messages.success(request, "Fornecedor ativado." if form.cleaned_data["ativo"] else "Fornecedor inativado.")
    return redirect("cadastros:fornecedor_listar")


@login_required
@require_http_methods(["GET", "POST"])
def fornecedor_excluir(request, pk):
    fornecedor = get_object_or_404(Fornecedor, pk=pk)
    if request.method == "POST":
        try:
            excluir_fornecedor(fornecedor_id=pk)
        except ValidationError as erro:
            for mensagem in erro.messages:
                messages.error(request, mensagem)
        except Fornecedor.DoesNotExist:
            raise Http404("Fornecedor não encontrado.") from None
        else:
            messages.success(request, "Fornecedor excluído.")
        return redirect("cadastros:fornecedor_listar")
    return render(request, "cadastros/fornecedor_confirmar_exclusao.html", {"fornecedor": fornecedor})


@login_required
@require_http_methods(["GET"])
def categoria_listar(request):
    filtro = FiltroCategoriaForm(request.GET)
    categorias = CategoriaAtivo.objects.all()
    tem_categorias = categorias.exists()
    if filtro.is_valid():
        termo = normalizar_identificador(filtro.cleaned_data["q"])
        if termo:
            categorias = categorias.filter(chave_nome__contains=termo)
        situacao = filtro.cleaned_data["situacao"]
        if situacao:
            categorias = categorias.filter(ativo=situacao == "ativas")
    else:
        categorias = categorias.none()
    pagina = Paginator(categorias, 15).get_page(request.GET.get("page"))
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(
        request, "cadastros/categoria_lista.html",
        {"filtro": filtro, "page_obj": pagina, "filtros_url": parametros.urlencode(),
         "tem_categorias": tem_categorias},
    )


def _formulario_categoria(request, categoria=None):
    form = CategoriaAtivoForm(
        request.POST if request.method == "POST" else None,
        initial={"nome": categoria.nome, "perfil_configuracao": categoria.perfil_configuracao} if categoria else None,
    )
    if request.method == "POST" and form.is_valid():
        try:
            salvar_categoria(**form.cleaned_data, categoria_id=categoria.pk if categoria else None)
        except ValidationError as erro:
            _adicionar_erros(form, erro)
        except CategoriaAtivo.DoesNotExist:
            raise Http404("Categoria não encontrada.") from None
        else:
            messages.success(request, "Categoria atualizada." if categoria else "Categoria cadastrada.")
            return redirect("cadastros:categoria_listar")
    return render(request, "cadastros/categoria_form.html", {"form": form, "categoria": categoria})


@login_required
@require_http_methods(["GET", "POST"])
def categoria_criar(request):
    return _formulario_categoria(request)


@login_required
@require_http_methods(["GET", "POST"])
def categoria_editar(request, pk):
    return _formulario_categoria(request, get_object_or_404(CategoriaAtivo, pk=pk))


@login_required
@require_POST
def categoria_iniciais(request):
    quantidade = adicionar_categorias_iniciais()
    if quantidade:
        messages.success(request, f"Categorias iniciais adicionadas: {quantidade}.")
    else:
        messages.info(request, "As categorias iniciais já estão cadastradas.")
    return redirect("cadastros:categoria_listar")


@login_required
@require_POST
def categoria_situacao(request, pk):
    form = SituacaoCadastroForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Situação inválida.")
    try:
        definir_situacao_categoria(categoria_id=pk, ativo=form.cleaned_data["ativo"])
    except CategoriaAtivo.DoesNotExist:
        raise Http404("Categoria não encontrada.") from None
    messages.success(request, "Categoria ativada." if form.cleaned_data["ativo"] else "Categoria inativada.")
    return redirect("cadastros:categoria_listar")


@login_required
@require_http_methods(["GET", "POST"])
def categoria_excluir(request, pk):
    categoria = get_object_or_404(CategoriaAtivo, pk=pk)
    if request.method == "POST":
        try:
            excluir_categoria(categoria_id=pk)
        except ValidationError as erro:
            for mensagem in erro.messages:
                messages.error(request, mensagem)
        except CategoriaAtivo.DoesNotExist:
            raise Http404("Categoria não encontrada.") from None
        else:
            messages.success(request, "Categoria excluída.")
        return redirect("cadastros:categoria_listar")
    return render(request, "cadastros/categoria_confirmar_exclusao.html", {"categoria": categoria})
