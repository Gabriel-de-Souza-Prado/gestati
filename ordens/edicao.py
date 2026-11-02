"""Edição de um serviço sem recriar o atendimento nem apagar seus efeitos anteriores."""
from collections import defaultdict
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from ativos.composicao import normalizar_itens_servico
from ativos.models import ComponenteInstalado, IntervencaoComponente
from estoque.models import Componente, MovimentoEstoque
from estoque.selectors import componentes_com_saldo
from .models import RegistroAtendimento, RevisaoServico
from .services import ESTADOS_TRABALHO, _bloquear_os, _chave, _texto, _versao


def itens_do_servico(registro):
    revisao = registro.revisoes.first()
    fonte = revisao.itens if revisao else registro.dados_confirmacao.get("dados", {}).get("itens", [])
    return [{k: i[k] for k in ("componente_id", "acao", "quantidade")} for i in fonte]


def _vetores(itens):
    composicao, estoque, acoes = defaultdict(int), defaultdict(int), defaultdict(dict)
    for i in itens:
        cid, q, acao = i["componente_id"], i["quantidade"], i["acao"]
        composicao[cid] += q if acao == "instalar" else -q
        estoque[cid] += -q if acao == "instalar" else q if acao == "retirar_reutilizar" else 0
        acoes[cid][acao] = q
    return composicao, estoque, acoes


def _repeticao(revisao, dados):
    if revisao.dados_confirmacao != dados:
        raise ValidationError("Esta confirmação já foi usada com outros dados. Reabra a edição.")
    return revisao, False


def editar_servico(*, ordem_id, registro_id, descricao, justificativa, itens, usuario, chave_confirmacao, versao, previa=None):
    chave = _chave(chave_confirmacao, usuario)
    descricao = _texto(descricao, "a descrição do serviço")
    justificativa = _texto(justificativa, "o motivo da edição", 3000)
    itens = normalizar_itens_servico(itens)
    registro = RegistroAtendimento.objects.filter(pk=registro_id, ordem_id=ordem_id, tipo="servico").first()
    if registro is None:
        raise ValidationError("Selecione um serviço realizado desta OS.")
    anteriores = itens_do_servico(registro)
    ids = {i["componente_id"] for i in anteriores + itens}
    dados = {"ordem_id": ordem_id, "registro_id": registro_id, "descricao": descricao, "justificativa": justificativa,
             "itens": itens, "usuario_id": usuario.pk, "versao": str(versao)}
    try:
        with transaction.atomic():
            componentes = {c.pk: c for c in Componente.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
            ativo, ordem = _bloquear_os(ordem_id)
            existente = RevisaoServico.objects.filter(chave_confirmacao=chave).first()
            if existente:
                return _repeticao(existente, dados)
            _versao(ordem, versao)
            if ordem.status not in ESTADOS_TRABALHO:
                raise ValidationError("Edite os serviços antes de concluir o trabalho técnico da OS.")
            if set(componentes) != ids:
                raise ValidationError("Uma especificação não existe mais no catálogo.")
            ultima = registro.revisoes.first()
            descricao_anterior = ultima.descricao if ultima else registro.descricao
            if descricao_anterior == descricao and anteriores == itens:
                raise ValidationError("O serviço informado é igual ao atual. Não há alteração a confirmar.")
            c0, e0, a0 = _vetores(anteriores)
            c1, e1, a1 = _vetores(itens)
            afetados = {cid for cid in ids if a0[cid] != a1[cid]}
            for cid in afetados:
                posteriores = ativo.intervencoes.filter(componente_id=cid, registrado_em__gte=registro.registrado_em).exclude(registro_os=registro).exclude(revisao_os__registro=registro)
                if posteriores.exists():
                    raise ValidationError(f'"{componentes[cid].nome}" teve alterações posteriores. Não é seguro desfazer este lançamento antigo; confira o serviço mais recente dessas peças.')
                if not componentes[cid].ativo and any(a1[cid].get(a, 0) > a0[cid].get(a, 0) for a in ("instalar", "retirar_reutilizar")):
                    raise ValidationError("Reative a especificação antes de aumentar instalação ou retorno ao estoque.")
            instalados = {l.componente_id: l for l in ativo.componentes_instalados.select_related("componente").order_by("componente_id")}
            antes = [{"componente_id": l.componente_id, "nome": l.componente.nome, "quantidade": l.quantidade} for l in instalados.values()]
            depois = {i["componente_id"]: dict(i) for i in antes}
            saldos = {c.pk: c.saldo for c in componentes_com_saldo().filter(pk__in=afetados)}
            efeitos, deltas = [], {}
            for cid in sorted(afetados):
                dc, de = c1[cid] - c0[cid], e1[cid] - e0[cid]
                base = (instalados[cid].quantidade if cid in instalados else 0) - c0[cid]
                retiradas = a1[cid].get("retirar_reutilizar", 0) + a1[cid].get("retirar_sem_retorno", 0)
                if base < 0 or retiradas > base:
                    raise ValidationError(f'As retiradas de "{componentes[cid].nome}" excedem o que estava instalado antes deste serviço.')
                if abs(dc) >= 2**31 or abs(de) >= 2**31:
                    raise ValidationError("Quantidade de ajuste acima do limite permitido. Confira as peças.")
                quantidade = (instalados[cid].quantidade if cid in instalados else 0) + dc
                if not 0 <= quantidade < 2**31:
                    raise ValidationError(f'Quantidade instalada inválida para "{componentes[cid].nome}". Confira as retiradas.')
                if saldos[cid] + de < 0:
                    raise ValidationError(f'Estoque insuficiente para corrigir "{componentes[cid].nome}". Nenhuma alteração foi confirmada.')
                if quantidade:
                    depois[cid] = {"componente_id": cid, "nome": componentes[cid].nome, "quantidade": quantidade}
                else:
                    depois.pop(cid, None)
                if de:
                    efeitos.append({"componente_id": cid, "nome": componentes[cid].nome, "tipo": "entrada" if de > 0 else "saida",
                                    "quantidade": abs(de), "antes": saldos[cid], "depois": saldos[cid] + de})
                deltas[cid] = (dc, de, quantidade)
            depois = [depois[cid] for cid in sorted(depois)]
            itens_salvos = [{**i, "nome": componentes[i["componente_id"]].nome} for i in itens]
            resumo = {"descricao_anterior": descricao_anterior, "antes": antes, "depois": depois,
                      "efeitos": efeitos, "itens": itens_salvos}
            if previa is None:
                return resumo, False
            if previa != resumo:
                raise ValidationError("A configuração ou os saldos mudaram após a prévia. Confira novamente antes de confirmar.")
            revisao = RevisaoServico(registro=registro, descricao=descricao, justificativa=justificativa, itens=itens_salvos,
                tecnico=usuario, nome_tecnico=usuario.get_full_name() or usuario.username, chave_confirmacao=chave,
                dados_confirmacao=dados, antes=antes, depois=depois, efeitos_estoque=efeitos)
            revisao.full_clean()
            revisao.save()
            for cid, (dc, de, quantidade) in deltas.items():
                componente = componentes[cid]
                if dc:
                    IntervencaoComponente.objects.create(ativo=ativo, componente=componente, quantidade=abs(dc), operacao=chave,
                        origem="ajuste_adicao" if dc > 0 else "ajuste_retirada", revisao_os=revisao, registrado_por=usuario,
                        nome_componente=componente.nome, dti_ativo=ativo.dti)
                    if quantidade:
                        ComponenteInstalado.objects.update_or_create(ativo=ativo, componente=componente, defaults={"quantidade": quantidade})
                    else:
                        ativo.componentes_instalados.filter(componente_id=cid).delete()
                if de:
                    evento = IntervencaoComponente.objects.create(ativo=ativo, componente=componente, quantidade=abs(de), operacao=chave,
                        origem="ajuste_estoque", revisao_os=revisao, registrado_por=usuario, nome_componente=componente.nome, dti_ativo=ativo.dti)
                    movimento = MovimentoEstoque(componente=componente, tipo="entrada" if de > 0 else "saida", origem="correcao",
                        quantidade=abs(de), data=timezone.localdate(), registrado_por=usuario, chave_confirmacao=uuid.uuid4(),
                        intervencao=evento, nome_componente=componente.nome, nome_tecnico=revisao.nome_tecnico,
                        observacao=f"Edição do serviço {registro.pk} da OS {ordem.pk}. {justificativa}"[:3000])
                    movimento.full_clean()
                    movimento.save()
                    Componente.objects.filter(pk=cid).update(acompanhar_estoque=True)
            if afetados:
                ativo.versao += 1
                ativo.save(update_fields=["versao", "atualizado_em"])
            ordem.versao += 1
            ordem.save(update_fields=["versao"])
            return revisao, True
    except IntegrityError as erro:
        if getattr(erro.__cause__, "sqlstate", None) == "23505":
            existente = RevisaoServico.objects.filter(chave_confirmacao=chave).first()
            if existente:
                return _repeticao(existente, dados)
        raise
