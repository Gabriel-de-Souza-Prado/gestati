from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class DadosMovimentacao(models.Model):
    """Dados comuns preservados na confirmação, sem depender do cadastro atual."""
    motivo = models.TextField(max_length=3000)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="%(class)s_registradas")
    registrado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    nome_tecnico = models.CharField(max_length=320)
    chave_confirmacao = models.UUIDField(unique=True, editable=False)
    dados_confirmacao = models.JSONField(editable=False)
    dti_ativo = models.CharField(max_length=64)
    patrimonio_ativo = models.CharField(max_length=64, blank=True)
    serie_ativo = models.CharField(max_length=120, blank=True)
    descricao_ativo = models.CharField(max_length=400)
    modelo_ativo = models.CharField(max_length=160, blank=True)
    nome_origem = models.CharField(max_length=160)
    nome_destino = models.CharField(max_length=160)

    class Meta:
        abstract = True
        ordering = ["-registrado_em", "-pk"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("A movimentação confirmada deve ser preservada. Registre outra operação quando necessário.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("O histórico de movimentações deve ser preservado.")


class TransferenciaAtivo(DadosMovimentacao):
    ativo = models.ForeignKey("ativos.Ativo", on_delete=models.PROTECT, related_name="transferencias")
    origem = models.ForeignKey("cadastros.Departamento", on_delete=models.PROTECT, related_name="transferencias_enviadas")
    destino = models.ForeignKey("cadastros.Departamento", on_delete=models.PROTECT, related_name="transferencias_recebidas")

    class Meta(DadosMovimentacao.Meta):
        abstract = False
        constraints = [
            models.CheckConstraint(condition=~models.Q(origem=models.F("destino")), name="transferencia_departamentos_diferentes"),
            models.CheckConstraint(condition=~models.Q(motivo=""), name="transferencia_motivo_obrigatorio"),
        ]


class EmprestimoAtivo(DadosMovimentacao):
    ativo = models.ForeignKey("ativos.Ativo", on_delete=models.PROTECT, related_name="emprestimos")
    origem = models.ForeignKey("cadastros.Departamento", on_delete=models.PROTECT, related_name="emprestimos_enviados")
    destino = models.ForeignKey("cadastros.Departamento", on_delete=models.PROTECT, related_name="emprestimos_recebidos")
    recebido_por = models.CharField("quem recebeu o empréstimo", max_length=160)
    encerrado_em = models.DateTimeField(null=True, blank=True)
    encerramento = models.CharField(max_length=16, choices=[("devolucao", "Devolvido"), ("transferencia", "Encerrado por transferência"), ("baixa", "Encerrado por baixa")], blank=True)
    transferencia_definitiva = models.OneToOneField(TransferenciaAtivo, on_delete=models.PROTECT, related_name="emprestimo_encerrado", null=True, blank=True)
    baixa_definitiva = models.OneToOneField("baixas.BaixaAtivo", on_delete=models.PROTECT, related_name="emprestimo_encerrado", null=True, blank=True)
    devolvido_em = models.DateTimeField(null=True, blank=True)
    devolvido_por = models.CharField("quem devolveu", max_length=160, blank=True)
    recebido_devolucao_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="emprestimos_devolvidos")
    nome_tecnico_devolucao = models.CharField(max_length=320, blank=True)
    observacoes_devolucao = models.TextField(max_length=3000, blank=True)
    chave_devolucao = models.UUIDField(unique=True, null=True, blank=True, editable=False)
    dados_devolucao = models.JSONField(null=True, blank=True, editable=False)

    class Meta(DadosMovimentacao.Meta):
        abstract = False
        constraints = [
            models.UniqueConstraint(fields=["ativo"], condition=models.Q(encerrado_em__isnull=True), name="emprestimo_um_ativo_por_equipamento"),
            models.CheckConstraint(condition=~models.Q(motivo="") & ~models.Q(recebido_por=""), name="emprestimo_motivo_recebedor_obrigatorios"),
            models.CheckConstraint(condition=(
                models.Q(encerrado_em__isnull=True, encerramento="", transferencia_definitiva__isnull=True, baixa_definitiva__isnull=True, devolvido_em__isnull=True, devolvido_por="", recebido_devolucao_por__isnull=True, nome_tecnico_devolucao="", chave_devolucao__isnull=True, dados_devolucao__isnull=True, observacoes_devolucao="")
                | (models.Q(encerrado_em__isnull=False, encerrado_em__gte=models.F("registrado_em"), encerramento="devolucao", transferencia_definitiva__isnull=True, baixa_definitiva__isnull=True, devolvido_em=models.F("encerrado_em"), devolvido_em__isnull=False, recebido_devolucao_por__isnull=False, chave_devolucao__isnull=False, dados_devolucao__isnull=False)
                   & ~models.Q(devolvido_por="") & ~models.Q(nome_tecnico_devolucao=""))
                | models.Q(encerrado_em__isnull=False, encerrado_em__gte=models.F("registrado_em"), encerramento="transferencia", transferencia_definitiva__isnull=False, baixa_definitiva__isnull=True, devolvido_em__isnull=True, devolvido_por="", recebido_devolucao_por__isnull=True, nome_tecnico_devolucao="", chave_devolucao__isnull=True, dados_devolucao__isnull=True, observacoes_devolucao="")
                | models.Q(encerrado_em__isnull=False, encerrado_em__gte=models.F("registrado_em"), encerramento="baixa", transferencia_definitiva__isnull=True, baixa_definitiva__isnull=False, devolvido_em__isnull=True, devolvido_por="", recebido_devolucao_por__isnull=True, nome_tecnico_devolucao="", chave_devolucao__isnull=True, dados_devolucao__isnull=True, observacoes_devolucao="")
            ), name="emprestimo_devolucao_coerente"),
        ]
