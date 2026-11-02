from functools import wraps
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from . import forms, services
from .models import Usuario


def administrador(view):
    @login_required
    @wraps(view)
    def protegida(request, *args, **kwargs):
        if not request.user.gerencia_usuarios:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return protegida


def erros(form, erro):
    if hasattr(erro, "message_dict"):
        for campo, mensagens in erro.message_dict.items():
            form.add_error(campo if campo in form.fields else None, mensagens)
    else:
        form.add_error(None, erro)


def pessoa_administravel(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    if usuario.is_superuser and not request.user.is_superuser:
        raise PermissionDenied
    return usuario


@administrador
@never_cache
@require_http_methods(["GET"])
def listar(request):
    termo = request.GET.get("q", "").strip()[:150]
    situacao = request.GET.get("situacao", "")
    usuarios = Usuario.objects.order_by("first_name", "username")
    if termo:
        usuarios = usuarios.filter(Q(username__icontains=termo) | Q(first_name__icontains=termo) | Q(last_name__icontains=termo))
    if situacao in {"ativos", "inativos"}:
        usuarios = usuarios.filter(is_active=situacao == "ativos")
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "contas/lista.html", {"page_obj": Paginator(usuarios, 15).get_page(request.GET.get("page")),
        "termo": termo, "situacao": situacao, "filtros_url": parametros.urlencode()})


@sensitive_post_parameters("senha_temporaria", "confirmar_senha")
@administrador
@never_cache
@require_http_methods(["GET", "POST"])
def criar(request):
    form = forms.NovoUsuarioForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        dados = form.cleaned_data.copy()
        senha_temporaria = dados.pop("senha_temporaria")
        dados.pop("confirmar_senha")
        try:
            services.salvar_usuario(autor=request.user, dados=dados, senha_temporaria=senha_temporaria)
        except ValidationError as erro:
            erros(form, erro)
        else:
            messages.success(request, "Conta criada. A troca da senha temporária será exigida no primeiro acesso.")
            return redirect("contas:listar")
    return render(request, "contas/form.html", {"form": form, "titulo": "Novo usuário", "novo": True})


@administrador
@never_cache
@require_http_methods(["GET", "POST"])
def editar(request, pk):
    usuario = pessoa_administravel(request, pk)
    form = forms.DadosUsuarioForm(request.POST if request.method == "POST" else None, usuario=usuario)
    if request.method == "POST" and form.is_valid():
        try:
            services.salvar_usuario(autor=request.user, dados=form.cleaned_data, usuario_id=pk, versao=form.cleaned_data["versao"])
        except ValidationError as erro:
            erros(form, erro)
        else:
            messages.success(request, "Dados da conta atualizados.")
            return redirect("contas:listar")
    return render(request, "contas/form.html", {"form": form, "titulo": "Editar usuário", "pessoa": usuario})


@sensitive_post_parameters("senha_temporaria", "confirmar_senha")
@administrador
@never_cache
@require_http_methods(["GET", "POST"])
def redefinir(request, pk):
    usuario = pessoa_administravel(request, pk)
    form = forms.RedefinirSenhaForm(request.POST if request.method == "POST" else None, initial={"versao": usuario.versao_acesso})
    if request.method == "POST" and form.is_valid():
        try:
            services.redefinir_senha(autor=request.user, usuario_id=pk, versao=form.cleaned_data["versao"],
                senha_temporaria=form.cleaned_data["senha_temporaria"])
        except ValidationError as erro:
            erros(form, erro)
        else:
            messages.success(request, "Senha temporária redefinida. O usuário precisará trocá-la ao entrar novamente.")
            return redirect("contas:listar")
    return render(request, "contas/redefinir.html", {"form": form, "pessoa": usuario})


@sensitive_post_parameters("old_password", "new_password1", "new_password2")
@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def senha(request):
    obrigatoria = request.user.deve_trocar_senha
    form = forms.SenhaPessoalForm(request.user, request.POST if request.method == "POST" else None)
    destino = request.POST.get("next", "") if request.method == "POST" else request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        destino = reverse("inicio")
    if destino.split("?", 1)[0] in {reverse("login"), reverse("logout"), reverse("contas:senha")}:
        destino = reverse("inicio")
    if request.method == "POST" and form.is_valid():
        try:
            usuario = services.trocar_senha(usuario_id=request.user.pk, senha_atual=form.cleaned_data["old_password"],
                nova_senha=form.cleaned_data["new_password1"])
        except ValidationError as erro:
            erros(form, erro)
        else:
            update_session_auth_hash(request, usuario)
            messages.success(request, "Senha pessoal definida. Seu acesso está liberado." if obrigatoria else "Senha atualizada.")
            return redirect(destino or "inicio")
    return render(request, "contas/senha.html", {"form": form, "obrigatoria": obrigatoria, "next": destino})
