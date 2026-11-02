"""Prévia e confirmação de configuração sem OS, com compensações rastreáveis."""
from collections import defaultdict
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from estoque.models import Componente, MovimentoEstoque
from estoque.selectors import componentes_com_saldo
from .composicao import normalizar_itens_servico, validar_composicao_completa
from .intervencoes import aplicar_itens_fisicos
from .models import Ativo, AlteracaoConfiguracao, ComponenteInstalado, IntervencaoComponente
from .regras import impedir_emprestimo_pendente


def _snapshot(ativo):
    return [{"componente_id": l.componente_id, "nome": l.componente.nome, "quantidade": l.quantidade}
            for l in ativo.componentes_instalados.select_related("componente").order_by("componente_id")]


def _repeticao(existente, dados):
    if existente.dados_confirmacao != dados:
        raise ValidationError("Esta confirmação já foi usada com outros dados. Reabra a alteração.")
    return existente, False


def alterar_configuracao(*, ativo_id, tipo, justificativa, usuario, chave_confirmacao,
                        versao, itens=None, intervencao_id=None, componente_id=None,
                        quantidade=None, previa=None):
    """Sem previa: simula em transação revertida. Com previa: revalida e confirma.

    O resultado completo é assinado pela view e comparado sob locks. Uma mudança
    de saldo/composição entre a prévia e o POST exige nova conferência.
    """
    if not getattr(usuario, "pk", None) or not usuario.is_active:
        raise ValidationError("A alteração exige usuário ativo da TI.")
    if tipo not in ("fisica", "correcao") or not isinstance(justificativa, str) or not justificativa.strip() or len(justificativa.strip()) > 3000:
        raise ValidationError("Informe o tipo e uma justificativa com até 3.000 caracteres.")
    try:
        chave = uuid.UUID(str(chave_confirmacao))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Confirmação inválida. Reabra a alteração.") from None
    itens = normalizar_itens_servico(itens or [])
    if tipo == "fisica" and not itens:
        raise ValidationError("Informe ao menos uma instalação ou retirada.")
    original = None
    if tipo == "correcao":
        if type(intervencao_id) is not int or type(quantidade) is not int or not 0 <= quantidade < 2**31:
            raise ValidationError("Selecione o lançamento a corrigir e a quantidade correta (zero remove o registro indevido).")
        original = IntervencaoComponente.objects.filter(pk=intervencao_id, ativo_id=ativo_id).first()
        if original is None or original.revisao_os_id or original.origem not in ("no_equipamento", "estoque", "ajuste_adicao"):
            raise ValidationError("Selecione uma inclusão de componentes deste ativo.")
        if quantidade and type(componente_id) is not int:
            raise ValidationError("Selecione a especificação correta.")
    ids = {i["componente_id"] for i in itens} if tipo == "fisica" else {original.componente_id}
    if tipo == "correcao" and quantidade:
        ids.add(componente_id)
    dados = {"ativo": ativo_id, "tipo": tipo, "justificativa": justificativa.strip(), "usuario": usuario.pk,
             "versao": str(versao), "itens": itens if tipo == "fisica" else [],
             "intervencao_id": intervencao_id if tipo == "correcao" else None,
             "componente_id": componente_id if tipo == "correcao" and quantidade else None,
             "quantidade": quantidade if tipo == "correcao" else None}
    try:
        with transaction.atomic():
            componentes = {c.pk: c for c in Componente.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
            if set(componentes) != ids:
                raise ValidationError("Um dos componentes não está mais disponível no catálogo.")
            ativo = Ativo.objects.select_for_update().get(pk=ativo_id)
            existente = AlteracaoConfiguracao.objects.filter(chave_confirmacao=chave).first()
            if existente:
                return _repeticao(existente, dados)
            if str(ativo.versao) != str(versao):
                raise ValidationError("O ativo mudou desde a abertura do formulário. Reabra e confira a configuração atual.")
            impedir_emprestimo_pendente(ativo)
            from core.perfis import PerfilConfiguracao as Perfil
            if ativo.categoria.perfil_configuracao not in (Perfil.COMPUTADOR, Perfil.NOTEBOOK):
                raise ValidationError("Alteração de componentes disponível somente para computadores e notebooks.")
            if ativo.situacao == Ativo.Situacao.BAIXADO:
                raise ValidationError("Ativo baixado não permite alteração de configuração.")
            if ativo.ordens_servico.exclude(status="encerrada").exists():
                raise ValidationError("Este ativo possui OS aberta. Registre a troca nela; para correção cadastral, regularize o atendimento antes de alterar sem OS.")
            antes = _snapshot(ativo)
            saldos_antes = {c.pk: c.saldo for c in componentes_com_saldo().filter(pk__in=ids)}
            registro = AlteracaoConfiguracao.objects.create(
                ativo=ativo, tipo=tipo, justificativa=justificativa.strip(), tecnico=usuario,
                nome_tecnico=usuario.get_full_name() or usuario.username,
                chave_confirmacao=chave, dados_confirmacao=dados, antes=antes, depois=[], efeitos_estoque=[],
                intervencao_corrigida=original,
            )
            if tipo == "fisica":
                aplicar_itens_fisicos(ativo=ativo, itens=itens, componentes=componentes, chave=chave, usuario=usuario, alteracao=registro)
            else:
                _corrigir(ativo, original, componente_id, quantidade, registro, componentes, usuario, chave)
            depois = _snapshot(ativo)
            if antes == depois and tipo == "correcao":
                raise ValidationError("A configuração informada é igual à atual. Não há correção a registrar.")
            validar_composicao_completa(ativo.categoria.perfil_configuracao, [l.componente for l in ativo.componentes_instalados.select_related("componente")])
            saldos_depois = {c.pk: c.saldo for c in componentes_com_saldo().filter(pk__in=ids)}
            # Mesmo saldo final pode envolver compensação e nova saída; mostrar ambos.
            movimentos = MovimentoEstoque.objects.filter(intervencao__alteracao=registro).select_related("componente").order_by("pk")
            efeitos = [{"componente_id": m.componente_id, "nome": m.nome_componente,
                        "tipo": m.tipo, "quantidade": m.quantidade,
                        "origem": m.origem} for m in movimentos]
            resumo = {"antes": antes, "depois": depois, "movimentos": efeitos,
                      "saldos": [{"componente_id": i, "nome": componentes[i].nome, "antes": saldos_antes[i], "depois": saldos_depois[i]} for i in sorted(ids)]}
            if previa is None:
                transaction.set_rollback(True)
                return resumo, False
            if previa != resumo:
                raise ValidationError("Os saldos ou a configuração mudaram após a prévia. Gere uma nova prévia antes de confirmar.")
            # Registro append-only: completar campos dentro da própria criação,
            # antes de publicar a confirmação da transação.
            AlteracaoConfiguracao.objects.filter(pk=registro.pk).update(depois=depois, efeitos_estoque=efeitos)
            registro.depois, registro.efeitos_estoque = depois, efeitos
            ativo.versao += 1
            ativo.save(update_fields=["versao", "atualizado_em"])
            return registro, True
    except IntegrityError as erro:
        if getattr(erro.__cause__, "sqlstate", None) == "23505":
            existente = AlteracaoConfiguracao.objects.filter(chave_confirmacao=chave).first()
            if existente:
                return _repeticao(existente, dados)
            raise ValidationError("Esse lançamento já foi corrigido. Confira a configuração atual.") from None
        raise


def _corrigir(ativo, original, novo_id, quantidade, registro, componentes, usuario, chave):
    if IntervencaoComponente.objects.filter(ativo=ativo, componente_id=original.componente_id, pk__gt=original.pk).exclude(operacao=original.operacao).exists():
        raise ValidationError("Esta peça teve intervenções posteriores. Corrija a inclusão mais recente ainda válida; não é seguro compensar um lançamento antigo já utilizado.")
    linha = ativo.componentes_instalados.filter(componente_id=original.componente_id).first()
    if linha is None or linha.quantidade < original.quantidade:
        raise ValidationError("O lançamento original não está mais integralmente instalado. Confira as intervenções posteriores.")
    if quantidade and not componentes[novo_id].ativo:
        raise ValidationError("Selecione uma especificação ativa para corrigir a configuração.")
    consumo = MovimentoEstoque.objects.filter(intervencao=original, tipo="saida").first()
    retirado = IntervencaoComponente.objects.create(ativo=ativo, componente_id=original.componente_id,
        quantidade=original.quantidade, operacao=chave, origem="ajuste_retirada", alteracao=registro,
        registrado_por=usuario, nome_componente=componentes[original.componente_id].nome, dti_ativo=ativo.dti)
    linha.quantidade -= original.quantidade
    if linha.quantidade:
        linha.save(update_fields=["quantidade"])
    else:
        linha.delete()
    if consumo:
        _compensar(retirado, "entrada", usuario, registro)
    if quantidade:
        existente = ativo.componentes_instalados.filter(componente_id=novo_id).first()
        novo_total = (existente.quantidade if existente else 0) + quantidade
        if novo_total >= 2**31:
            raise ValidationError("Quantidade instalada acima do limite permitido.")
        if existente:
            existente.quantidade = novo_total
            existente.save(update_fields=["quantidade"])
        else:
            ComponenteInstalado.objects.create(ativo=ativo, componente_id=novo_id, quantidade=quantidade)
        adicionado = IntervencaoComponente.objects.create(ativo=ativo, componente_id=novo_id,
            quantidade=quantidade, operacao=chave, origem="ajuste_adicao", alteracao=registro,
            registrado_por=usuario, nome_componente=componentes[novo_id].nome, dti_ativo=ativo.dti)
        if consumo:
            _compensar(adicionado, "saida", usuario, registro)


def _compensar(evento, tipo, usuario, registro):
    if tipo == "saida" and componentes_com_saldo().get(pk=evento.componente_id).saldo < evento.quantidade:
        raise ValidationError("Estoque insuficiente da especificação correta. A correção inteira foi revertida; confira os recebimentos físicos.")
    movimento = MovimentoEstoque(componente_id=evento.componente_id, tipo=tipo, origem="correcao",
        quantidade=evento.quantidade, data=timezone.localdate(), registrado_por=usuario,
        chave_confirmacao=uuid.uuid4(), intervencao=evento, nome_componente=evento.nome_componente,
        nome_tecnico=registro.nome_tecnico, observacao=f"Correção vinculada ao lançamento {registro.intervencao_corrigida_id}. {registro.justificativa}")
    # Justificativa limitada, mantendo observação dentro do campo.
    movimento.observacao = movimento.observacao[:3000]
    movimento.full_clean()
    movimento.save()
    Componente.objects.filter(pk=evento.componente_id).update(acompanhar_estoque=True)
