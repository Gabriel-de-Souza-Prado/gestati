"""Casos de uso de OS: sem HttpRequest, HTML ou dados fornecidos pelo navegador sobre o saldo."""
from collections import defaultdict
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from ativos.models import Ativo, ComponenteInstalado, IntervencaoComponente
from ativos.regras import impedir_emprestimo_pendente
from ativos.composicao import validar_composicao_completa, normalizar_itens_servico
from ativos.intervencoes import aplicar_itens_fisicos
from core.normalizacao import padronizar_espacos
from estoque.models import Componente
from estoque.services import registrar_retorno_intervencao, registrar_saida_intervencao
from .models import OrdemServico as OS, RegistroAtendimento as Registro


ESTADOS_TRABALHO = (OS.Status.ABERTA, OS.Status.EM_ATENDIMENTO, OS.Status.AGUARDANDO_PECA)


def _chave(valor, usuario):
    if not getattr(usuario, "pk", None) or not usuario.is_active:
        raise ValidationError("A operação exige usuário ativo da TI.")
    try:
        return uuid.UUID(str(valor))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Confirmação inválida. Reabra o formulário.") from None


def _texto(valor, rotulo, maximo=5000):
    if not isinstance(valor, str) or not valor.strip() or len(valor.strip()) > maximo:
        raise ValidationError(f"Informe {rotulo}, com até {maximo} caracteres.")
    return valor.strip()


def _repeticao(registro, payload, campo="dados_confirmacao"):
    if getattr(registro, campo) != payload:
        raise ValidationError("Esta confirmação já foi usada com outros dados. Reabra o formulário.")
    return registro, False


def abrir_os(*, ativo_id, entregue_por, problema, usuario, chave_confirmacao):
    chave = _chave(chave_confirmacao, usuario)
    entregue_por = padronizar_espacos(_texto(entregue_por, "o nome de quem entregou", 160))
    problema = _texto(problema, "o problema informado")
    payload = {"ativo": ativo_id, "entregue_por": entregue_por, "problema": problema, "usuario": usuario.pk}
    try:
        with transaction.atomic():
            ativo = Ativo.objects.select_for_update().get(pk=ativo_id)
            existente = OS.objects.filter(chave_abertura=chave).first()
            if existente:
                return _repeticao(existente, payload, "dados_abertura")
            impedir_emprestimo_pendente(ativo)
            if ativo.ordens_servico.exclude(status=OS.Status.ENCERRADA).exists():
                raise ValidationError("Este ativo já possui uma OS em aberto, inclusive aguardando coleta. Continue o atendimento existente.")
            if ativo.situacao not in (Ativo.Situacao.EM_USO, Ativo.Situacao.RESERVA):
                raise ValidationError("Para abrir uma OS, o ativo precisa estar Em uso ou Em reserva. Confira a situação e os atendimentos anteriores.")
            ordem = OS(
                ativo=ativo, departamento=ativo.departamento, entregue_por=entregue_por, problema=problema,
                situacao_anterior=ativo.situacao, aberto_por=usuario,
                chave_abertura=chave, dados_abertura=payload,
                dti_ativo=ativo.dti, patrimonio_ativo=ativo.patrimonio or "", serie_ativo=ativo.numero_serie,
                nome_ativo=ativo.descricao, modelo_ativo=ativo.modelo, nome_departamento=ativo.departamento.nome,
                nome_tecnico_abertura=usuario.get_full_name() or usuario.username,
                garantia_na_abertura=ativo.esta_em_garantia(), fim_garantia=ativo.fim_garantia,
                nome_fornecedor=ativo.fornecedor.nome if ativo.fornecedor_id else "",
            )
            ordem.full_clean()
            ordem.save()
            ativo.situacao = Ativo.Situacao.EM_MANUTENCAO
            ativo.versao += 1
            ativo.save(update_fields=["situacao", "versao", "atualizado_em"])
            return ordem, True
    except IntegrityError as erro:
        if getattr(erro.__cause__, "sqlstate", None) == "23505":
            existente = OS.objects.filter(chave_abertura=chave).first()
            if existente:
                return _repeticao(existente, payload, "dados_abertura")
            raise ValidationError("Já existe uma OS aberta para este ativo. Consulte o atendimento existente.") from None
        raise


def _bloquear_os(ordem_id):
    # Componentes (quando houver), ativo e OS: sempre nesta ordem.
    # Sem select_related no lock para não bloquear fornecedores/cadastros de apoio.
    ativo_id = OS.objects.values_list("ativo_id", flat=True).get(pk=ordem_id)
    ativo = Ativo.objects.select_for_update().get(pk=ativo_id)
    return ativo, OS.objects.select_for_update().get(pk=ordem_id)


def _versao(ordem, versao):
    if str(ordem.versao) != str(versao):
        raise ValidationError("Esta OS foi alterada por outro atendimento. Reabra o formulário e confira os dados atuais.")


def _confirmar(*, ordem_id, tipo, descricao, dados, usuario, chave_confirmacao, executar):
    chave = _chave(chave_confirmacao, usuario)
    descricao = _texto(descricao, "a descrição do atendimento")
    payload = {"ordem": ordem_id, "tipo": tipo, "descricao": descricao, "dados": dados, "usuario": usuario.pk}
    try:
        with transaction.atomic():
            # serializa peças entre OS/ativos distintos, antes dos locks do ativo/OS.
            ids = sorted({item["componente_id"] for item in dados.get("itens", [])})
            componentes = {c.pk: c for c in Componente.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
            if set(componentes) != set(ids):
                raise ValidationError("Uma das especificações de componente não existe. Confira as peças.")
            ativo, ordem = _bloquear_os(ordem_id)
            existente = Registro.objects.filter(chave_confirmacao=chave).first()
            if existente:
                return _repeticao(existente, payload)
            _versao(ordem, dados["versao"])
            registro = Registro(ordem=ordem, tipo=tipo, descricao=descricao, tecnico=usuario,
                                nome_tecnico=usuario.get_full_name() or usuario.username,
                                chave_confirmacao=chave, dados_confirmacao=payload)
            registro.full_clean()
            registro.save()
            executar(ativo, ordem, registro, componentes, chave)
            ordem.versao += 1
            ordem.full_clean()
            ordem.save()
            return registro, True
    except IntegrityError as erro:
        if getattr(erro.__cause__, "sqlstate", None) == "23505":
            existente = Registro.objects.filter(chave_confirmacao=chave).first()
            if existente:
                return _repeticao(existente, payload)
        raise


def atualizar_andamento(*, ordem_id, status, descricao, usuario, chave_confirmacao, versao):
    if status not in (OS.Status.EM_ATENDIMENTO, OS.Status.AGUARDANDO_PECA):
        raise ValidationError("Escolha Em atendimento ou Aguardando peça.")

    def executar(ativo, ordem, registro, componentes, chave):
        if ordem.status not in ESTADOS_TRABALHO:
            raise ValidationError("O andamento só pode mudar enquanto o trabalho técnico está pendente.")
        if ordem.status == status:
            raise ValidationError("A OS já está nessa etapa. Registre o trabalho na opção Serviço realizado.")
        ordem.status = status

    return _confirmar(ordem_id=ordem_id, tipo=Registro.Tipo.ANDAMENTO, descricao=descricao,
                     dados={"status": status, "versao": str(versao)}, usuario=usuario,
                     chave_confirmacao=chave_confirmacao, executar=executar)


def registrar_servico(*, ordem_id, descricao, itens, usuario, chave_confirmacao, versao):
    itens = normalizar_itens_servico(itens)

    def executar(ativo, ordem, registro, componentes, chave):
        if ordem.status not in ESTADOS_TRABALHO:
            raise ValidationError("Não é possível lançar serviços após a conclusão técnica da OS.")
        aplicar_itens_fisicos(ativo=ativo, itens=itens, componentes=componentes, chave=chave,
                              usuario=usuario, registro_os=registro)
        if ordem.status == OS.Status.ABERTA:
            ordem.status = OS.Status.EM_ATENDIMENTO
        if itens:
            ativo.versao += 1
            ativo.save(update_fields=["versao", "atualizado_em"])

    return _confirmar(ordem_id=ordem_id, tipo=Registro.Tipo.SERVICO, descricao=descricao,
                     dados={"itens": itens, "versao": str(versao)}, usuario=usuario,
                     chave_confirmacao=chave_confirmacao, executar=executar)


def concluir_os(*, ordem_id, resultado, descricao, usuario, chave_confirmacao, versao):
    if resultado not in OS.Resultado.values:
        raise ValidationError("Informe Reparado ou Sem reparo.")

    def executar(ativo, ordem, registro, componentes, chave):
        if ordem.status not in ESTADOS_TRABALHO:
            raise ValidationError("Esta OS já possui uma conclusão técnica.")
        if resultado == OS.Resultado.REPARADO:
            validar_composicao_completa(ativo.categoria.perfil_configuracao, [l.componente for l in ativo.componentes_instalados.select_related("componente")])
        ordem.status = OS.Status.AGUARDANDO_COLETA
        ordem.resultado = resultado
        ordem.concluido_em = timezone.now()
        # A entrega ainda está pendente, mesmo quando o resultado foi Reparado.
        ativo.situacao = Ativo.Situacao.SEM_REPARO if resultado == OS.Resultado.SEM_REPARO else Ativo.Situacao.EM_MANUTENCAO
        ativo.versao += 1
        ativo.save(update_fields=["situacao", "versao", "atualizado_em"])

    return _confirmar(ordem_id=ordem_id, tipo=Registro.Tipo.CONCLUSAO, descricao=descricao,
                     dados={"resultado": resultado, "versao": str(versao)}, usuario=usuario,
                     chave_confirmacao=chave_confirmacao, executar=executar)


def encerrar_os(*, ordem_id, recebido_por, para_baixa, usuario, chave_confirmacao, versao):
    if type(para_baixa) is not bool:
        raise ValidationError("Confirme a forma de encerramento.")
    if para_baixa:
        if recebido_por:
            raise ValidationError("O encerramento para baixa dispensa recebedor.")
        nome = ""
    else:
        nome = padronizar_espacos(_texto(recebido_por, "o nome de quem recebeu o equipamento", 160))

    def executar(ativo, ordem, registro, componentes, chave):
        if ordem.status != OS.Status.AGUARDANDO_COLETA:
            raise ValidationError("Conclua o trabalho técnico antes de encerrar a OS.")
        if para_baixa and ordem.resultado != OS.Resultado.SEM_REPARO:
            raise ValidationError("Encerrar para baixa exige resultado Sem reparo.")
        ordem.status = OS.Status.ENCERRADA
        ordem.encerrado_em = timezone.now()
        ordem.recebido_por = nome
        ordem.encerrada_para_baixa = para_baixa
        ativo.situacao = Ativo.Situacao.SEM_REPARO if ordem.resultado == OS.Resultado.SEM_REPARO else ordem.situacao_anterior
        ativo.versao += 1
        ativo.save(update_fields=["situacao", "versao", "atualizado_em"])

    return _confirmar(ordem_id=ordem_id, tipo=Registro.Tipo.PARA_BAIXA if para_baixa else Registro.Tipo.DEVOLUCAO,
                     descricao="Encerrada para baixa. Equipamento permanece na TI, sem retirada." if para_baixa else f"Equipamento recebido por {nome}.",
                     dados={"recebido_por": nome, "para_baixa": para_baixa, "versao": str(versao)}, usuario=usuario,
                     chave_confirmacao=chave_confirmacao, executar=executar)
