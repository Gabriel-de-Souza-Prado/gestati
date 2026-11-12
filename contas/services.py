"""Regras de contas: sem dependência de HTTP, senhas sempre pelo Django."""
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.views.decorators.debug import sensitive_variables

from .models import Usuario


def _administrar(autor):
    # Contas da equipe são poucas. A ordem única também serializa ações de
    # administradores diferentes, evitando desativação/destituição recíproca.
    usuarios = {u.pk: u for u in Usuario.objects.select_for_update().order_by("pk")}
    atual = usuarios.get(autor.pk)
    if atual is None or not atual.gerencia_usuarios or atual.deve_trocar_senha:
        raise PermissionDenied("Somente um administrador ativo pode gerenciar contas.")
    return usuarios, atual


def _versao(usuario, versao):
    if str(usuario.versao_acesso) != str(versao):
        raise ValidationError("Esta conta mudou desde que você abriu a tela. Reabra para conferir os dados atuais.")


@sensitive_variables("senha")
def _senha(usuario, senha, campo="senha_temporaria"):
    if not isinstance(senha, str) or len(senha) > 4096:
        raise ValidationError({campo: "Informe uma senha válida, com até 4096 caracteres."})
    try:
        validate_password(senha, user=usuario)
    except ValidationError as erro:
        raise ValidationError({campo: erro.messages}) from None
    if usuario.check_password(senha):
        raise ValidationError({campo: "Escolha uma senha diferente da atual."})


@sensitive_variables("senha_temporaria")
@transaction.atomic
def salvar_usuario(*, autor, dados, usuario_id=None, versao=None, senha_temporaria=None):
    usuarios, administrador = _administrar(autor)
    novo = usuario_id is None
    usuario = Usuario() if novo else usuarios.get(usuario_id)
    if usuario is None:
        raise ValidationError("Usuário não encontrado.")
    if usuario.is_superuser and not administrador.is_superuser:
        raise PermissionDenied("A conta técnica só pode ser alterada por um administrador técnico.")
    if not novo:
        _versao(usuario, versao)
    perfil = dados.get("perfil")
    if perfil not in {"ti", "administrador"}:
        raise ValidationError("Selecione um perfil válido.")
    ativo = dados.get("ativo")
    if type(ativo) is not bool:
        raise ValidationError("Informe a situação da conta.")
    admin_desejado = perfil == "administrador"
    if not novo and usuario.is_superuser and not admin_desejado:
        raise ValidationError("O perfil da conta técnica inicial é preservado nesta tela.")
    if not novo and usuario.pk == administrador.pk and (not ativo or not admin_desejado):
        raise ValidationError("Você não pode inativar a própria conta ou retirar seu próprio acesso administrativo.")
    outros_admins = Usuario.objects.exclude(pk=usuario.pk).filter(is_active=True).filter(
        models_admins()).exists()
    if not novo and usuario.gerencia_usuarios and (not ativo or not admin_desejado) and not outros_admins:
        raise ValidationError("Mantenha pelo menos um administrador ativo.")
    username = Usuario.normalize_username(str(dados.get("username", "")).strip())
    if Usuario.objects.exclude(pk=usuario.pk).filter(username__iexact=username).exists():
        raise ValidationError({"username": "Já existe uma conta com esse usuário, inclusive entre inativos."})
    usuario.username = username
    usuario.first_name = str(dados.get("nome", "")).strip()
    usuario.last_name = str(dados.get("sobrenome", "")).strip()
    usuario.email = str(dados.get("email", "")).strip()
    if not usuario.first_name:
        raise ValidationError({"nome": "Informe o nome."})
    usuario.is_active = ativo
    # Administrador TI não recebe is_staff/is_superuser ou permissões técnicas.
    usuario.administrador_ti = admin_desejado and not usuario.is_superuser
    if novo:
        if not senha_temporaria:
            raise ValidationError("Informe a senha temporária.")
        _senha(usuario, senha_temporaria)
        usuario.set_password(senha_temporaria)
        usuario.deve_trocar_senha = True
    else:
        usuario.versao_acesso += 1
    usuario.full_clean()
    usuario.save()
    return usuario


def models_admins():
    from django.db.models import Q
    return Q(is_superuser=True) | Q(administrador_ti=True)


@sensitive_variables("senha_temporaria")
@transaction.atomic
def redefinir_senha(*, autor, usuario_id, versao, senha_temporaria):
    usuarios, administrador = _administrar(autor)
    usuario = usuarios.get(usuario_id)
    if usuario is None:
        raise ValidationError("Usuário não encontrado.")
    if usuario.is_superuser and not administrador.is_superuser:
        raise PermissionDenied("A conta técnica só pode ser alterada por um administrador técnico.")
    if usuario.pk == administrador.pk:
        raise ValidationError("Para sua própria conta, use Alterar minha senha.")
    _versao(usuario, versao)
    _senha(usuario, senha_temporaria)
    usuario.set_password(senha_temporaria)
    usuario.deve_trocar_senha = True
    usuario.versao_acesso += 1
    usuario.save(update_fields=["password", "deve_trocar_senha", "versao_acesso"])
    return usuario


@sensitive_variables("senha_atual", "nova_senha")
@transaction.atomic
def trocar_senha(*, usuario_id, senha_atual, nova_senha):
    usuario = Usuario.objects.select_for_update().get(pk=usuario_id)
    if not usuario.is_active:
        raise PermissionDenied("Conta inativa.")
    if not usuario.check_password(senha_atual):
        raise ValidationError({"old_password": "A senha atual não confere. Informe novamente."})
    _senha(usuario, nova_senha, campo="new_password2")
    usuario.set_password(nova_senha)
    usuario.deve_trocar_senha = False
    usuario.versao_acesso += 1
    usuario.save(update_fields=["password", "deve_trocar_senha", "versao_acesso"])
    return usuario
