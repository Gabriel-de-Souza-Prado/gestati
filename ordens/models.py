from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class OrdemServico(models.Model):
    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        EM_ATENDIMENTO = "em_atendimento", "Em atendimento"
        AGUARDANDO_PECA = "aguardando_peca", "Aguardando peça"
        AGUARDANDO_COLETA = "aguardando_coleta", "Aguardando coleta"
        ENCERRADA = "encerrada", "Encerrada"

    class Resultado(models.TextChoices):
        REPARADO = "reparado", "Reparado"
        SEM_REPARO = "sem_reparo", "Sem reparo"

    ativo = models.ForeignKey("ativos.Ativo", on_delete=models.PROTECT, related_name="ordens_servico")
    departamento = models.ForeignKey("cadastros.Departamento", on_delete=models.PROTECT, related_name="ordens_servico")
    entregue_por = models.CharField("quem entregou o equipamento", max_length=160)
    problema = models.TextField("problema informado", max_length=5000)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ABERTA, db_index=True)
    resultado = models.CharField(max_length=16, choices=Resultado.choices, blank=True)
    situacao_anterior = models.CharField(max_length=16, choices=[("em_uso", "Em uso"), ("reserva", "Em reserva")])
    aberto_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ordens_abertas")
    aberto_em = models.DateTimeField(auto_now_add=True, db_index=True)
    concluido_em = models.DateTimeField(null=True, blank=True)
    encerrado_em = models.DateTimeField(null=True, blank=True)
    recebido_por = models.CharField("quem recebeu na devolução", max_length=160, blank=True)
    encerrada_para_baixa = models.BooleanField(default=False)
    versao = models.PositiveIntegerField(default=1)
    chave_abertura = models.UUIDField(unique=True, editable=False)
    dados_abertura = models.JSONField(editable=False)
    # Identificação preservada para consultar/imprimir mesmo após mudanças cadastrais.
    dti_ativo = models.CharField(max_length=64)
    patrimonio_ativo = models.CharField(max_length=64, blank=True)
    serie_ativo = models.CharField(max_length=120, blank=True)
    nome_ativo = models.CharField(max_length=160)
    modelo_ativo = models.CharField(max_length=160, blank=True)
    nome_departamento = models.CharField(max_length=160)
    nome_tecnico_abertura = models.CharField(max_length=320)
    garantia_na_abertura = models.BooleanField(default=False)
    fim_garantia = models.DateField(null=True, blank=True)
    nome_fornecedor = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["-aberto_em", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["ativo"], condition=~models.Q(status="encerrada"), name="os_uma_aberta_por_ativo"),
            models.CheckConstraint(condition=~models.Q(entregue_por="") & ~models.Q(problema=""), name="os_entrega_problema_obrigatorios"),
            models.CheckConstraint(condition=models.Q(situacao_anterior__in=["em_uso", "reserva"]), name="os_situacao_anterior_valida"),
            models.CheckConstraint(condition=(
                models.Q(status__in=["aberta", "em_atendimento", "aguardando_peca"], resultado="", concluido_em__isnull=True, encerrado_em__isnull=True, recebido_por="", encerrada_para_baixa=False)
                | models.Q(status="aguardando_coleta", resultado__in=["reparado", "sem_reparo"], concluido_em__isnull=False, encerrado_em__isnull=True, recebido_por="", encerrada_para_baixa=False)
                | (models.Q(status="encerrada", resultado__in=["reparado", "sem_reparo"], concluido_em__isnull=False, encerrado_em__isnull=False) & (
                    models.Q(encerrada_para_baixa=True, resultado="sem_reparo", recebido_por="")
                    | (models.Q(encerrada_para_baixa=False) & ~models.Q(recebido_por=""))
                ))
            ), name="os_estado_datas_resultado_coerentes"),
        ]

    def __str__(self):
        return f"OS {self.pk} · DTI {self.dti_ativo}"


class RegistroAtendimento(models.Model):
    class Tipo(models.TextChoices):
        ANDAMENTO = "andamento", "Atualização de andamento"
        SERVICO = "servico", "Serviço realizado"
        CONCLUSAO = "conclusao", "Conclusão técnica"
        DEVOLUCAO = "devolucao", "Devolução"
        PARA_BAIXA = "para_baixa", "Encerramento para baixa"

    ordem = models.ForeignKey(OrdemServico, on_delete=models.PROTECT, related_name="registros")
    tipo = models.CharField(max_length=16, choices=Tipo.choices)
    descricao = models.TextField(max_length=5000)
    tecnico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registros_atendimento")
    nome_tecnico = models.CharField(max_length=320)
    registrado_em = models.DateTimeField(auto_now_add=True)
    chave_confirmacao = models.UUIDField(unique=True, editable=False)
    dados_confirmacao = models.JSONField(editable=False)

    class Meta:
        ordering = ["registrado_em", "pk"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("O atendimento confirmado deve ser preservado. Correções exigem uma operação própria.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Os serviços e confirmações da OS devem ser preservados.")


class RevisaoServico(models.Model):
    registro = models.ForeignKey(RegistroAtendimento, on_delete=models.PROTECT, related_name="revisoes")
    descricao = models.TextField(max_length=5000)
    justificativa = models.TextField(max_length=3000)
    itens = models.JSONField(default=list, blank=True)
    tecnico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="revisoes_servico")
    nome_tecnico = models.CharField(max_length=320)
    registrado_em = models.DateTimeField(auto_now_add=True)
    chave_confirmacao = models.UUIDField(unique=True, editable=False)
    dados_confirmacao = models.JSONField(editable=False)
    antes = models.JSONField(default=list, blank=True)
    depois = models.JSONField(default=list, blank=True)
    efeitos_estoque = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-registrado_em", "-pk"]
        constraints = [models.CheckConstraint(condition=~models.Q(descricao="") & ~models.Q(justificativa=""), name="revisao_servico_textos_obrigatorios")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("A edição confirmada deve ser preservada. Registre uma nova edição.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("O histórico de edições do serviço deve ser preservado.")
