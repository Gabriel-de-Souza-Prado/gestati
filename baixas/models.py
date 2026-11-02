from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class BaixaAtivo(models.Model):
    ativo = models.OneToOneField("ativos.Ativo", on_delete=models.PROTECT, related_name="baixa")
    ordem = models.OneToOneField("ordens.OrdemServico", on_delete=models.PROTECT, null=True, blank=True, related_name="baixa")
    departamento = models.ForeignKey("cadastros.Departamento", on_delete=models.PROTECT, related_name="baixas")
    motivo = models.TextField(max_length=3000)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="baixas")
    registrado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    nome_tecnico = models.CharField(max_length=320)
    chave_confirmacao = models.UUIDField(unique=True, editable=False)
    dados_confirmacao = models.JSONField(editable=False)
    dti_ativo = models.CharField(max_length=64)
    patrimonio_ativo = models.CharField(max_length=64, blank=True)
    serie_ativo = models.CharField(max_length=120, blank=True)
    descricao_ativo = models.CharField(max_length=400)
    nome_departamento = models.CharField(max_length=160)
    situacao_anterior = models.CharField(max_length=16, choices=[("em_uso", "Em uso"), ("reserva", "Em reserva"), ("sem_reparo", "Sem reparo")])
    configuracao_anterior = models.JSONField(default=list, blank=True, editable=False)
    recuperados = models.JSONField(default=list, blank=True, editable=False)
    configuracao_remanescente = models.JSONField(default=list, blank=True, editable=False)

    class Meta:
        ordering = ["-registrado_em", "-pk"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(motivo=""), name="baixa_motivo_obrigatorio"),
            models.CheckConstraint(condition=models.Q(situacao_anterior__in=["em_uso", "reserva", "sem_reparo"]), name="baixa_situacao_anterior_valida"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("A baixa confirmada deve ser preservada.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("O documento e o histórico da baixa devem ser preservados.")
