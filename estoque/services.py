import re
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils import timezone

from cadastros.models import Fornecedor

from .models import Componente, MovimentoEstoque


def salvar_componente(*, nome, tipo, descricao="", capacidade=None, unidade_capacidade="", quantidade_minima=0, componente_id=None, acompanhar_estoque=None):
    if not re.fullmatch(r"[0-9]+", str(quantidade_minima)):
        raise ValidationError({"quantidade_minima": "Informe um mínimo inteiro maior ou igual a zero."})
    try:
        with transaction.atomic():
            componente = Componente.objects.select_for_update().get(pk=componente_id) if componente_id is not None else Componente()
            especificacao_anterior = (componente.tipo, componente.capacidade, componente.unidade_capacidade)
            componente.nome, componente.tipo, componente.descricao = nome, tipo, descricao
            componente.capacidade, componente.unidade_capacidade = capacidade, unidade_capacidade
            componente.quantidade_minima = quantidade_minima
            if acompanhar_estoque is not None:
                if not acompanhar_estoque and componente.pk and componente.movimentos.exists():
                    raise ValidationError("Uma especificação com movimentação deve continuar no estoque, mesmo quando o saldo zera.")
                componente.acompanhar_estoque = acompanhar_estoque
            componente.preparar_identificacao()
            componente.full_clean()
            especificacao_nova = (componente.tipo, componente.capacidade, componente.unidade_capacidade)
            if componente.pk and especificacao_nova != especificacao_anterior and (componente.movimentos.exists() or componente.instalacoes.exists() or componente.intervencoes.exists()):
                raise ValidationError("Este componente já foi utilizado. Para outra capacidade ou tipo, cadastre uma nova especificação. Nome, descrição e mínimo continuam editáveis.")
            componente.save()
            return componente
    except IntegrityError as erro:
        if getattr(erro.__cause__, "sqlstate", None) != "23505":
            raise
        raise ValidationError({"nome": "Já existe um componente com esse nome/especificação, inclusive entre os inativos."}) from None
    except ValidationError as erro:
        if hasattr(erro, "message_dict") and "chave_nome" in erro.message_dict:
            mensagens = dict(erro.message_dict)
            mensagens["nome"] = ["Já existe um componente com esse nome/especificação, inclusive entre os inativos."]
            mensagens.pop("chave_nome")
            raise ValidationError(mensagens) from None
        raise


@transaction.atomic
def definir_situacao_componente(*, componente_id, ativo):
    componente = Componente.objects.select_for_update().get(pk=componente_id)
    componente.ativo = ativo
    componente.save(update_fields=["ativo", "atualizado_em"])
    return componente


@transaction.atomic
def excluir_componente(*, componente_id):
    componente = Componente.objects.select_for_update().get(pk=componente_id)
    try:
        componente.delete()
    except (ProtectedError, RestrictedError):
        raise ValidationError("Este componente possui registros vinculados e não pode ser excluído. Inative-o para preservar o histórico.") from None


def _conferir_repeticao(existente, pretendido):
    campos = ("componente_id", "tipo", "origem", "quantidade", "data", "fornecedor_id", "registrado_por_id", "observacao")
    if any(getattr(existente, campo) != getattr(pretendido, campo) for campo in campos):
        raise ValidationError("Esta confirmação já foi usada com outros dados. Abra uma nova entrada para registrar outro recebimento.")
    return existente, False


def registrar_entrada(*, componente_id, quantidade, origem, data, usuario, chave_confirmacao, fornecedor_id=None, observacao=""):
    """Uma confirmação representa um recebimento, inclusive sob reenvio simultâneo."""
    if not getattr(usuario, "pk", None) or not usuario.is_active:
        raise ValidationError("O registro exige um usuário ativo da TI.")
    if origem not in (MovimentoEstoque.Origem.COMPRA, MovimentoEstoque.Origem.SALDO_INICIAL, MovimentoEstoque.Origem.OUTRA_ENTRADA):
        raise ValidationError({"origem": "Selecione uma origem de recebimento manual."})
    if not re.fullmatch(r"[0-9]+", str(quantidade)):
        raise ValidationError({"quantidade": "Informe uma quantidade inteira maior que zero."})
    try:
        chave = uuid.UUID(str(chave_confirmacao))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Confirmação inválida. Reabra o formulário de entrada.") from None
    movimento = MovimentoEstoque(
        componente_id=componente_id, quantidade=quantidade, tipo=MovimentoEstoque.Tipo.ENTRADA,
        origem=origem, data=data, fornecedor_id=fornecedor_id, registrado_por=usuario,
        chave_confirmacao=chave, observacao=(observacao or "").strip(),
    )
    # Validar formato/FKs sem exigir snapshots ainda não preenchidos nem rejeitar reenvio.
    movimento.full_clean(exclude=["nome_componente", "nome_fornecedor", "nome_tecnico"], validate_unique=False)
    try:
        with transaction.atomic():
            componente = Componente.objects.select_for_update().get(pk=movimento.componente_id)
            existente = MovimentoEstoque.objects.filter(chave_confirmacao=chave).first()
            if existente:
                return _conferir_repeticao(existente, movimento)
            if not componente.ativo:
                raise ValidationError({"componente": "Este componente está inativo. Reative-o antes de registrar uma nova entrada."})
            fornecedor = None
            if movimento.fornecedor_id:
                fornecedor = Fornecedor.objects.select_for_update().get(pk=movimento.fornecedor_id)
                if not fornecedor.ativo:
                    raise ValidationError({"fornecedor": "Este fornecedor está inativo. Selecione um fornecedor ativo ou deixe sem fornecedor."})
            movimento.nome_componente = componente.nome
            movimento.nome_fornecedor = fornecedor.nome if fornecedor else ""
            movimento.nome_tecnico = usuario.get_full_name() or usuario.username
            movimento.full_clean(validate_unique=False)
            movimento.save()
            if not componente.acompanhar_estoque:
                componente.acompanhar_estoque = True
                componente.save(update_fields=["acompanhar_estoque", "atualizado_em"])
            return movimento, True
    except IntegrityError as erro:
        if getattr(erro.__cause__, "sqlstate", None) != "23505":
            raise
        existente = MovimentoEstoque.objects.filter(chave_confirmacao=chave).first()
        if existente is None:
            raise
        return _conferir_repeticao(existente, movimento)


@transaction.atomic
def registrar_saida_intervencao(*, intervencao, usuario):
    """Consome apenas uma intervenção persistida, nunca uma saída avulsa."""
    from ativos.models import IntervencaoComponente
    from .selectors import componentes_com_saldo

    if not getattr(usuario, "pk", None) or not usuario.is_active or not intervencao.pk:
        raise ValidationError("A aplicação exige usuário ativo e intervenção registrada.")
    componente = Componente.objects.select_for_update().get(pk=intervencao.componente_id)
    evento = IntervencaoComponente.objects.get(pk=intervencao.pk)
    if evento.componente_id != componente.pk or evento.origem != "estoque" or evento.registrado_por_id != usuario.pk:
        raise ValidationError("A intervenção não corresponde à aplicação de peças deste técnico.")
    existente = MovimentoEstoque.objects.filter(intervencao=evento).first()
    if existente:
        return existente
    if not componente.ativo:
        raise ValidationError(f'O componente "{componente.nome}" está inativo.')
    saldo = componentes_com_saldo().get(pk=componente.pk).saldo
    if saldo < evento.quantidade:
        raise ValidationError(f'Estoque insuficiente para "{componente.nome}": disponível {saldo}, necessário {evento.quantidade}.')
    movimento = MovimentoEstoque(
        componente=componente, tipo=MovimentoEstoque.Tipo.SAIDA, origem=MovimentoEstoque.Origem.APLICACAO,
        quantidade=evento.quantidade, data=timezone.localdate(), registrado_por=usuario,
        chave_confirmacao=uuid.uuid4(), intervencao=evento, nome_componente=componente.nome,
        nome_tecnico=usuario.get_full_name() or usuario.username,
        observacao=f"Composição do ativo DTI {evento.dti_ativo}.",
    )
    movimento.full_clean()
    movimento.save()
    if not componente.acompanhar_estoque:
        componente.acompanhar_estoque = True
        componente.save(update_fields=["acompanhar_estoque", "atualizado_em"])
    return movimento


@transaction.atomic
def registrar_retorno_intervencao(*, intervencao, usuario):
    """Recebe somente peças explicitamente retiradas para reutilização em operação vinculada."""
    from ativos.models import IntervencaoComponente

    if not getattr(usuario, "pk", None) or not usuario.is_active or not intervencao.pk:
        raise ValidationError("O retorno exige usuário ativo e intervenção registrada.")
    componente = Componente.objects.select_for_update().get(pk=intervencao.componente_id)
    evento = IntervencaoComponente.objects.get(pk=intervencao.pk)
    if (evento.componente_id != componente.pk or evento.origem != "retorno_estoque"
            or not (evento.registro_os_id or evento.alteracao_id or evento.baixa_id) or evento.registrado_por_id != usuario.pk):
        raise ValidationError("O retorno exige uma retirada para reutilização vinculada ao atendimento, alteração de configuração ou baixa.")
    existente = MovimentoEstoque.objects.filter(intervencao=evento).first()
    if existente:
        return existente
    if not componente.ativo:
        raise ValidationError(f'Reative o componente "{componente.nome}" antes de devolvê-lo ao estoque.')
    movimento = MovimentoEstoque(
        componente=componente, tipo=MovimentoEstoque.Tipo.ENTRADA, origem=MovimentoEstoque.Origem.RECUPERACAO_BAIXA if evento.baixa_id else MovimentoEstoque.Origem.RETORNO_OS,
        quantidade=evento.quantidade, data=timezone.localdate(), registrado_por=usuario,
        chave_confirmacao=uuid.uuid4(), intervencao=evento, nome_componente=componente.nome,
        nome_tecnico=usuario.get_full_name() or usuario.username,
        observacao=f"Peça recuperada do ativo DTI {evento.dti_ativo}.",
    )
    movimento.full_clean()
    movimento.save()
    if not componente.acompanhar_estoque:
        componente.acompanhar_estoque = True
        componente.save(update_fields=["acompanhar_estoque", "atualizado_em"])
    return movimento
