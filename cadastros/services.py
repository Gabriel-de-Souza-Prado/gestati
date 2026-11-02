from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from core.perfis import PerfilConfiguracao

from .models import (
    CategoriaAtivo, Departamento, Fornecedor, IdentificadorDepartamento,
    normalizar_identificador,
)


def salvar_departamento(*, nome, sigla="", departamento_id=None):
    """Salva identificação e índice de nome/sigla como uma única operação."""
    try:
        with transaction.atomic():
            departamento = (
                Departamento.objects.select_for_update().get(pk=departamento_id)
                if departamento_id is not None
                else Departamento()
            )
            departamento.nome = nome
            departamento.sigla = sigla
            departamento.preparar_identificacao()
            departamento.full_clean()

            chaves = {departamento.chave_nome: "nome"}
            if departamento.sigla:
                chaves.setdefault(normalizar_identificador(departamento.sigla), "sigla")
            conflitos = IdentificadorDepartamento.objects.filter(chave__in=chaves)
            if departamento.pk:
                conflitos = conflitos.exclude(departamento_id=departamento.pk)
            erros = {}
            for conflito in conflitos.select_related("departamento"):
                campo = chaves[conflito.chave]
                erros[campo] = (
                    f'Essa identificação já pertence a "{conflito.departamento.nome}". '
                    "Consulte ou edite o cadastro existente."
                )
            if erros:
                raise ValidationError(erros)

            departamento.save()
            departamento.identificadores.exclude(chave__in=chaves).delete()
            for chave in sorted(chaves):
                IdentificadorDepartamento.objects.get_or_create(
                    chave=chave, defaults={"departamento": departamento}
                )
                # get_or_create pode encontrar um identificador confirmado por
                # outra transação; conferir o dono antes de concluir.
                if not departamento.identificadores.filter(chave=chave).exists():
                    raise ValidationError(
                        "Já existe um departamento com esse nome ou sigla."
                    )
            return departamento
    except IntegrityError:
        raise ValidationError(
            "Já existe um departamento com esse nome ou sigla. Consulte a lista."
        ) from None
    except ValidationError as erro:
        if hasattr(erro, "message_dict") and "chave_nome" in erro.message_dict:
            mensagens = dict(erro.message_dict)
            mensagens["nome"] = mensagens.pop("chave_nome")
            raise ValidationError(mensagens) from None
        raise


@transaction.atomic
def definir_situacao_departamento(*, departamento_id, ativo):
    departamento = Departamento.objects.select_for_update().get(pk=departamento_id)
    departamento.ativo = ativo
    departamento.save(update_fields=["ativo", "atualizado_em"])
    return departamento


@transaction.atomic
def excluir_departamento(*, departamento_id):
    departamento = Departamento.objects.select_for_update().get(pk=departamento_id)
    # Os identificadores são internos ao cadastro, não vínculos de utilização.
    # Os próximos módulos usarão PROTECT nas referências a departamentos.
    _garantir_sem_vinculos(departamento, ignorar_modelos=(IdentificadorDepartamento,))
    try:
        departamento.delete()
    except (ProtectedError, RestrictedError):
        raise ValidationError(
            "Este departamento possui registros vinculados. Inative-o para preservar o histórico."
        ) from None


def _garantir_sem_vinculos(registro, *, ignorar_modelos=()):
    for relacao in registro._meta.related_objects:
        if relacao.related_model in ignorar_modelos:
            continue
        if relacao.one_to_many or relacao.one_to_one:
            if relacao.related_model._base_manager.filter(
                **{relacao.field.name: registro}
            ).exists():
                raise ValidationError(
                    "Existem registros vinculados a este cadastro. Não é possível excluí-lo. "
                    "A inativação permite preservar o histórico."
                )


def salvar_fornecedor(*, nome, cnpj=None, telefone="", email="", fornecedor_id=None):
    try:
        with transaction.atomic():
            fornecedor = (
                Fornecedor.objects.select_for_update().get(pk=fornecedor_id)
                if fornecedor_id is not None else Fornecedor()
            )
            fornecedor.nome = nome
            fornecedor.cnpj = cnpj
            fornecedor.telefone = telefone
            fornecedor.email = email
            fornecedor.preparar_identificacao()
            fornecedor.full_clean()
            fornecedor.save()
            return fornecedor
    except IntegrityError as erro:
        if getattr(erro.__cause__, "sqlstate", None) != "23505":
            raise
        raise ValidationError({"cnpj": "Já existe um fornecedor com esse CNPJ, inclusive entre os inativos."}) from None


@transaction.atomic
def definir_situacao_fornecedor(*, fornecedor_id, ativo):
    fornecedor = Fornecedor.objects.select_for_update().get(pk=fornecedor_id)
    fornecedor.ativo = ativo
    fornecedor.save(update_fields=["ativo", "atualizado_em"])
    return fornecedor


@transaction.atomic
def excluir_fornecedor(*, fornecedor_id):
    fornecedor = Fornecedor.objects.select_for_update().get(pk=fornecedor_id)
    _garantir_sem_vinculos(fornecedor)
    try:
        fornecedor.delete()
    except (ProtectedError, RestrictedError):
        raise ValidationError(
            "Este fornecedor possui registros vinculados. Inative-o para preservar o histórico."
        ) from None


def salvar_categoria(*, nome, categoria_id=None, perfil_configuracao=None):
    try:
        with transaction.atomic():
            categoria = (
                CategoriaAtivo.objects.select_for_update().get(pk=categoria_id)
                if categoria_id is not None else CategoriaAtivo()
            )
            categoria.nome = nome
            if perfil_configuracao is not None:
                if categoria.pk and categoria.perfil_configuracao != perfil_configuracao and categoria.ativos.exists():
                    raise ValidationError({"perfil_configuracao": "Esta categoria já tem ativos. Cadastre outra categoria para usar um perfil diferente, preservando os dados existentes."})
                categoria.perfil_configuracao = perfil_configuracao
            categoria.preparar_identificacao()
            categoria.full_clean()
            categoria.save()
            return categoria
    except IntegrityError as erro:
        if getattr(erro.__cause__, "sqlstate", None) != "23505":
            raise
        raise ValidationError({"nome": "Já existe uma categoria com esse nome, inclusive entre as inativas."}) from None
    except ValidationError as erro:
        if hasattr(erro, "message_dict") and "chave_nome" in erro.message_dict:
            mensagens = dict(erro.message_dict)
            mensagens["nome"] = mensagens.pop("chave_nome")
            raise ValidationError(mensagens) from None
        raise


@transaction.atomic
def adicionar_categorias_iniciais():
    """Atalho explícito e repetível; não modifica categorias já cadastradas."""
    novas = 0
    for nome in ("Computador", "Monitor", "Nobreak", "Notebook", "Switch"):
        _, criada = CategoriaAtivo.objects.get_or_create(
            chave_nome=normalizar_identificador(nome), defaults={"nome": nome, "perfil_configuracao": {
                "Computador": PerfilConfiguracao.COMPUTADOR, "Monitor": PerfilConfiguracao.MONITOR,
                "Nobreak": PerfilConfiguracao.NOBREAK, "Notebook": PerfilConfiguracao.NOTEBOOK,
                "Switch": PerfilConfiguracao.SWITCH,
            }[nome]},
        )
        novas += int(criada)
    return novas


@transaction.atomic
def definir_situacao_categoria(*, categoria_id, ativo):
    categoria = CategoriaAtivo.objects.select_for_update().get(pk=categoria_id)
    categoria.ativo = ativo
    categoria.save(update_fields=["ativo", "atualizado_em"])
    return categoria


@transaction.atomic
def excluir_categoria(*, categoria_id):
    categoria = CategoriaAtivo.objects.select_for_update().get(pk=categoria_id)
    _garantir_sem_vinculos(categoria)
    try:
        categoria.delete()
    except (ProtectedError, RestrictedError):
        raise ValidationError(
            "Esta categoria possui registros vinculados. Inative-a para preservar o histórico."
        ) from None
