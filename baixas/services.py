"""Baixa e recuperação indivisíveis, independentes de HTTP e de geração de PDF."""
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from ativos.intervencoes import aplicar_itens_fisicos
from ativos.models import Ativo
from estoque.models import Componente
from estoque.selectors import componentes_com_saldo
from movimentacoes.models import EmprestimoAtivo
from .models import BaixaAtivo


def _itens(itens):
    if not isinstance(itens, list) or len(itens) > 200:
        raise ValidationError("Informe até 200 especificações a recuperar.")
    resultado, ids = [], set()
    for item in itens:
        if not isinstance(item, dict):
            raise ValidationError("Seleção de recuperação inválida.")
        cid, quantidade = item.get("componente_id"), item.get("quantidade")
        if type(cid) is not int or cid <= 0 or type(quantidade) is not int or not 0 < quantidade < 2**31 or cid in ids:
            raise ValidationError("Selecione cada componente uma vez, com quantidade inteira positiva.")
        ids.add(cid)
        resultado.append({"componente_id": cid, "quantidade": quantidade})
    return sorted(resultado, key=lambda i: i["componente_id"])


def _repeticao(registro, dados):
    if registro.dados_confirmacao != dados:
        raise ValidationError("Esta confirmação já foi usada com outros dados. Reabra a baixa.")
    return registro, False


def baixar_ativo(*, ativo_id, motivo, itens, usuario, chave_confirmacao, versao, ordem_id=None, previa=None):
    """Sem previa retorna conferência sem gravar; com previa revalida sob os mesmos locks.

    Ordem global: componentes selecionados por PK → ativo → empréstimo pendente → OS de origem.
    Reenvio da mesma confirmação retorna o evento, sem retirar/receber novamente.
    """
    if not getattr(usuario, "pk", None) or not usuario.is_active:
        raise ValidationError("A baixa exige usuário ativo da TI.")
    if not isinstance(motivo, str) or not motivo.strip() or len(motivo.strip()) > 3000:
        raise ValidationError("Informe o motivo da baixa, com até 3.000 caracteres.")
    try:
        chave = uuid.UUID(str(chave_confirmacao))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Confirmação inválida. Reabra a baixa.") from None
    itens = _itens(itens)
    dados = {"ativo_id": ativo_id, "motivo": motivo.strip(), "itens": itens,
             "usuario_id": usuario.pk, "versao": str(versao), "ordem_id": ordem_id}
    try:
        with transaction.atomic():
            ids = {i["componente_id"] for i in itens}
            componentes = {c.pk: c for c in Componente.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
            ativo = Ativo.objects.select_for_update().get(pk=ativo_id)
            existente = BaixaAtivo.objects.filter(chave_confirmacao=chave).first()
            if existente:
                return _repeticao(existente, dados)
            if ativo.situacao == Ativo.Situacao.BAIXADO or BaixaAtivo.objects.filter(ativo=ativo).exists():
                raise ValidationError("Este equipamento já foi baixado. Consulte o documento existente.")
            if str(ativo.versao) != str(versao):
                raise ValidationError("O ativo mudou. Reabra a baixa e confira sua configuração atual.")
            if ativo.ordens_servico.exclude(status="encerrada").exists():
                raise ValidationError("Encerre a OS antes de confirmar a baixa. Aguardando coleta também é uma OS aberta.")
            emprestimo = EmprestimoAtivo.objects.select_for_update().filter(ativo=ativo, encerrado_em__isnull=True).first()
            if ativo.situacao not in ("em_uso", "reserva", "sem_reparo"):
                raise ValidationError("Regularize a manutenção antes de confirmar a baixa.")
            ordem = None
            if ordem_id is not None:
                ordem = ativo.ordens_servico.select_for_update().filter(pk=ordem_id, status="encerrada", encerrada_para_baixa=True).first()
                if ordem is None:
                    raise ValidationError("A OS de origem deve pertencer ao ativo e estar encerrada para baixa.")
            instalados = list(ativo.componentes_instalados.select_related("componente").order_by("componente_id"))
            antes = [{"componente_id": l.componente_id, "nome": l.componente.nome, "quantidade": l.quantidade} for l in instalados]
            por_id = {l.componente_id: l for l in instalados}
            saldos = {c.pk: c.saldo for c in componentes_com_saldo().filter(pk__in=ids)}
            recuperados = []
            for item in itens:
                cid, qtd = item["componente_id"], item["quantidade"]
                if cid not in por_id or qtd > por_id[cid].quantidade:
                    raise ValidationError("A recuperação deve respeitar os componentes e quantidades instalados neste ativo.")
                if cid not in componentes or not componentes[cid].ativo:
                    raise ValidationError("Reative a especificação no catálogo antes de recuperá-la para o estoque.")
                recuperados.append({**item, "nome": componentes[cid].nome, "saldo_antes": saldos[cid], "saldo_depois": saldos[cid] + qtd})
            retirar = {i["componente_id"]: i["quantidade"] for i in itens}
            depois = [{**l, "quantidade": l["quantidade"] - retirar.get(l["componente_id"], 0)} for l in antes if l["quantidade"] > retirar.get(l["componente_id"], 0)]
            resumo = {"dti": ativo.dti, "patrimonio": ativo.patrimonio or "", "descricao": ativo.descricao,
                      "departamento": ativo.departamento.nome, "situacao": ativo.situacao,
                      "antes": antes, "recuperados": recuperados, "depois": depois,
                      "emprestimo": {"id": emprestimo.pk, "destino": emprestimo.nome_destino} if emprestimo else None}
            if previa is None:
                return resumo, False
            if previa != resumo:
                raise ValidationError("A configuração ou os saldos mudaram após a prévia. Gere uma nova prévia para conferir.")
            registro = BaixaAtivo(
                ativo=ativo, ordem=ordem, departamento=ativo.departamento, motivo=motivo.strip(), registrado_por=usuario,
                nome_tecnico=usuario.get_full_name() or usuario.username, chave_confirmacao=chave, dados_confirmacao=dados,
                dti_ativo=ativo.dti, patrimonio_ativo=ativo.patrimonio or "", serie_ativo=ativo.numero_serie,
                descricao_ativo=ativo.descricao, nome_departamento=ativo.departamento.nome, situacao_anterior=ativo.situacao,
                configuracao_anterior=antes, recuperados=recuperados, configuracao_remanescente=depois,
            )
            registro.full_clean()
            registro.save()
            aplicar_itens_fisicos(ativo=ativo, itens=[{**i, "acao": "retirar_reutilizar"} for i in itens],
                                 componentes=componentes, chave=chave, usuario=usuario, baixa=registro)
            if emprestimo:
                # Encerramento automático confirmado pelo usuário; não inventar devolução física.
                EmprestimoAtivo.objects.filter(pk=emprestimo.pk, encerrado_em__isnull=True).update(
                    encerrado_em=registro.registrado_em, encerramento="baixa", baixa_definitiva=registro)
            ativo.situacao = Ativo.Situacao.BAIXADO
            ativo.versao += 1
            ativo.save(update_fields=["situacao", "versao", "atualizado_em"])
            return registro, True
    except IntegrityError as erro:
        if getattr(erro.__cause__, "sqlstate", None) == "23505":
            existente = BaixaAtivo.objects.filter(chave_confirmacao=chave).first()
            if existente:
                return _repeticao(existente, dados)
        raise
