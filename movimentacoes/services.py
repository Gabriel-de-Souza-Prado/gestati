"""Transferência definitiva e empréstimo temporário com histórico e concorrência."""
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from ativos.models import Ativo
from ativos.regras import impedir_emprestimo_pendente
from cadastros.models import Departamento
from core.normalizacao import padronizar_espacos
from .models import EmprestimoAtivo, TransferenciaAtivo


def _chave(valor, usuario):
    if not getattr(usuario, "pk", None) or not usuario.is_active:
        raise ValidationError("A movimentação exige usuário ativo da TI.")
    try:
        return uuid.UUID(str(valor))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Confirmação inválida. Reabra o formulário.") from None


def _texto(valor, rotulo, limite=3000):
    if not isinstance(valor, str) or not valor.strip() or len(valor.strip()) > limite:
        raise ValidationError(f"Informe {rotulo}, com até {limite} caracteres.")
    return valor.strip()


def _repeticao(registro, dados, campo="dados_confirmacao"):
    if getattr(registro, campo) != dados:
        raise ValidationError("Esta confirmação já foi usada com outros dados. Reabra o formulário.")
    return registro, False


def _validar_ativo(ativo, versao, *, transferencia=False):
    if str(ativo.versao) != str(versao):
        raise ValidationError("O ativo mudou desde a abertura do formulário. Reabra a movimentação e confira os dados atuais.")
    if ativo.situacao not in (Ativo.Situacao.EM_USO, Ativo.Situacao.RESERVA):
        raise ValidationError("O ativo precisa estar Em uso ou Em reserva, sem manutenção ou baixa pendente.")
    if ativo.ordens_servico.exclude(status="encerrada").exists():
        raise ValidationError("O ativo tem uma OS aberta, inclusive aguardando coleta. Encerre o atendimento antes de movimentar.")
    if not transferencia:
        impedir_emprestimo_pendente(ativo)


def _registrar(*, modelo, ativo_id, destino_id, motivo, usuario, chave_confirmacao, versao, recebido_por=""):
    chave = _chave(chave_confirmacao, usuario)
    motivo = _texto(motivo, "o motivo")
    dados = {"ativo_id": ativo_id, "destino_id": destino_id, "motivo": motivo,
             "usuario_id": usuario.pk, "versao": str(versao), "recebido_por": recebido_por}
    try:
        with transaction.atomic():
            # Ativo primeiro. Estes fluxos não bloqueiam componentes;
            # destino é bloqueado depois, como na edição de metadados.
            ativo = Ativo.objects.select_for_update().get(pk=ativo_id)
            existente = modelo.objects.filter(chave_confirmacao=chave).first()
            if existente:
                return _repeticao(existente, dados)
            _validar_ativo(ativo, versao, transferencia=modelo is TransferenciaAtivo)
            emprestimo = EmprestimoAtivo.objects.select_for_update().filter(ativo=ativo, encerrado_em__isnull=True).first() if modelo is TransferenciaAtivo else None
            try:
                destino = Departamento.objects.select_for_update().get(pk=destino_id, ativo=True)
            except (Departamento.DoesNotExist, ValueError, TypeError):
                raise ValidationError("Selecione um departamento de destino ativo.") from None
            if modelo is TransferenciaAtivo and destino.pk == ativo.departamento_id:
                raise ValidationError("O destino deve ser diferente do departamento atual.")
            valores = {
                "ativo": ativo, "origem": ativo.departamento, "destino": destino,
                "motivo": motivo, "registrado_por": usuario, "nome_tecnico": usuario.get_full_name() or usuario.username,
                "chave_confirmacao": chave, "dados_confirmacao": dados,
                "dti_ativo": ativo.dti, "patrimonio_ativo": ativo.patrimonio or "", "serie_ativo": ativo.numero_serie,
                "descricao_ativo": ativo.descricao, "modelo_ativo": ativo.modelo,
                "nome_origem": ativo.departamento.nome, "nome_destino": destino.nome,
            }
            if modelo is EmprestimoAtivo:
                valores["recebido_por"] = recebido_por
            registro = modelo(**valores)
            registro.full_clean()
            registro.save()
            if modelo is TransferenciaAtivo:
                ativo.departamento = destino
                if emprestimo:
                    # Conversão em definitivo, sem devolução fictícia.
                    EmprestimoAtivo.objects.filter(pk=emprestimo.pk, encerrado_em__isnull=True).update(
                        encerrado_em=timezone.now(), encerramento="transferencia", transferencia_definitiva=registro)
            # Empréstimo não altera vínculo/situação cadastrada; presença do
            # empréstimo ativo determina indisponibilidade temporária.
            ativo.versao += 1
            ativo.save(update_fields=["departamento", "versao", "atualizado_em"] if modelo is TransferenciaAtivo else ["versao", "atualizado_em"])
            return registro, True
    except IntegrityError as erro:
        if getattr(erro.__cause__, "sqlstate", None) == "23505":
            existente = modelo.objects.filter(chave_confirmacao=chave).first()
            if existente:
                return _repeticao(existente, dados)
            raise ValidationError("Já existe empréstimo ativo para este equipamento. Confira as movimentações.") from None
        raise


def transferir_ativo(*, ativo_id, destino_id, motivo, usuario, chave_confirmacao, versao):
    return _registrar(modelo=TransferenciaAtivo, ativo_id=ativo_id, destino_id=destino_id, motivo=motivo,
                      usuario=usuario, chave_confirmacao=chave_confirmacao, versao=versao)


def emprestar_ativo(*, ativo_id, destino_id, recebido_por, motivo, usuario, chave_confirmacao, versao):
    recebido_por = padronizar_espacos(_texto(recebido_por, "o nome de quem recebeu o empréstimo", 160))
    return _registrar(modelo=EmprestimoAtivo, ativo_id=ativo_id, destino_id=destino_id, motivo=motivo,
                      recebido_por=recebido_por, usuario=usuario, chave_confirmacao=chave_confirmacao, versao=versao)


def devolver_emprestimo(*, emprestimo_id, devolvido_por, usuario, chave_confirmacao, versao, observacoes=""):
    chave = _chave(chave_confirmacao, usuario)
    nome = padronizar_espacos(_texto(devolvido_por, "o nome de quem devolveu", 160))
    if not isinstance(observacoes, str) or len(observacoes.strip()) > 3000:
        raise ValidationError("Observações devem ter até 3.000 caracteres.")
    dados = {"emprestimo_id": emprestimo_id, "devolvido_por": nome, "usuario_id": usuario.pk,
             "versao": str(versao), "observacoes": observacoes.strip()}
    try:
        with transaction.atomic():
            ativo_id = EmprestimoAtivo.objects.values_list("ativo_id", flat=True).get(pk=emprestimo_id)
            ativo = Ativo.objects.select_for_update().get(pk=ativo_id)
            emprestimo = EmprestimoAtivo.objects.select_for_update().get(pk=emprestimo_id)
            existente = EmprestimoAtivo.objects.filter(chave_devolucao=chave).first()
            if existente:
                return _repeticao(existente, dados, "dados_devolucao")
            if emprestimo.encerrado_em:
                raise ValidationError("Este empréstimo já foi encerrado por devolução, transferência ou baixa.")
            if str(ativo.versao) != str(versao):
                raise ValidationError("O ativo mudou. Reabra a devolução e confira os dados atuais.")
            emprestimo.devolvido_em = timezone.now()
            emprestimo.encerrado_em = emprestimo.devolvido_em
            emprestimo.encerramento = "devolucao"
            emprestimo.devolvido_por = nome
            emprestimo.recebido_devolucao_por = usuario
            emprestimo.nome_tecnico_devolucao = usuario.get_full_name() or usuario.username
            emprestimo.chave_devolucao = chave
            emprestimo.dados_devolucao = dados
            emprestimo.observacoes_devolucao = observacoes.strip()
            emprestimo.full_clean()
            EmprestimoAtivo.objects.filter(pk=emprestimo.pk, encerrado_em__isnull=True).update(
                encerrado_em=emprestimo.encerrado_em, encerramento="devolucao",
                devolvido_em=emprestimo.devolvido_em, devolvido_por=nome, recebido_devolucao_por=usuario,
                nome_tecnico_devolucao=emprestimo.nome_tecnico_devolucao, chave_devolucao=chave,
                dados_devolucao=dados, observacoes_devolucao=observacoes.strip(),
            )
            ativo.versao += 1
            ativo.save(update_fields=["versao", "atualizado_em"])
            return emprestimo, True
    except IntegrityError as erro:
        if getattr(erro.__cause__, "sqlstate", None) == "23505":
            existente = EmprestimoAtivo.objects.filter(chave_devolucao=chave).first()
            if existente:
                return _repeticao(existente, dados, "dados_devolucao")
        raise
