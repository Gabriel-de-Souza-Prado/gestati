from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.normalizacao import normalizar_identificador, padronizar_espacos


class Componente(models.Model):
    acompanhar_estoque = models.BooleanField("controlar peças no estoque", default=True)
    class Tipo(models.TextChoices):
        MEMORIA_RAM = "ram", "Memória RAM"
        SSD = "ssd", "SSD"
        HDD = "hdd", "HDD"
        FONTE = "fonte", "Fonte"
        PLACA_MAE = "placa_mae", "Placa-mãe"
        PROCESSADOR = "processador", "Processador"
        OUTRO = "outro", "Outro componente"

    class UnidadeCapacidade(models.TextChoices):
        GB = "GB", "GB"
        TB = "TB", "TB"

    nome = models.CharField("nome/especificação", max_length=160)
    tipo = models.CharField("tipo", max_length=16, choices=Tipo.choices)
    descricao = models.TextField("descrição", max_length=3000, blank=True)
    capacidade = models.DecimalField("capacidade por unidade", max_digits=9, decimal_places=2, null=True, blank=True)
    unidade_capacidade = models.CharField("unidade da capacidade", max_length=2, choices=UnidadeCapacidade.choices, blank=True)
    quantidade_minima = models.PositiveIntegerField("estoque mínimo", default=0)
    ativo = models.BooleanField(default=True)
    chave_nome = models.CharField(max_length=320, unique=True, editable=False, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chave_nome", "pk"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(chave_nome=""), name="componente_nome_nao_vazio"),
            models.CheckConstraint(condition=models.Q(tipo__in=["ram", "ssd", "hdd", "fonte", "placa_mae", "processador", "outro"]), name="componente_tipo_valido"),
            models.CheckConstraint(
                condition=(
                    models.Q(tipo="ram", capacidade__isnull=False, capacidade__gt=0, unidade_capacidade="GB")
                    | models.Q(tipo__in=["ssd", "hdd"], capacidade__isnull=False, capacidade__gt=0, unidade_capacidade__in=["GB", "TB"])
                    | (~models.Q(tipo__in=["ram", "ssd", "hdd"]) & models.Q(capacidade__isnull=True, unidade_capacidade=""))
                ), name="componente_capacidade_valida",
            ),
        ]

    def preparar_identificacao(self):
        self.nome = padronizar_espacos(self.nome)
        self.chave_nome = normalizar_identificador(self.nome)
        self.descricao = (self.descricao or "").strip()

    def clean(self):
        super().clean()
        self.preparar_identificacao()
        erros = {}
        if not self.chave_nome:
            erros["nome"] = "Informe o nome e a especificação do componente."
        if self.tipo in (self.Tipo.MEMORIA_RAM, self.Tipo.SSD, self.Tipo.HDD):
            if not isinstance(self.capacidade, Decimal) or not self.capacidade.is_finite() or self.capacidade <= 0:
                erros["capacidade"] = "Informe uma capacidade maior que zero para cada unidade."
            if self.unidade_capacidade not in self.UnidadeCapacidade.values:
                erros["unidade_capacidade"] = "Selecione GB ou TB."
            elif self.tipo == self.Tipo.MEMORIA_RAM and self.unidade_capacidade != "GB":
                erros["unidade_capacidade"] = "Informe a capacidade da memória RAM em GB."
        elif self.capacidade is not None or self.unidade_capacidade:
            erros["capacidade"] = "Capacidade em GB/TB é usada apenas para RAM, SSD e HDD."
        if erros:
            raise ValidationError(erros)

    def save(self, *args, **kwargs):
        self.preparar_identificacao()
        if kwargs.get("update_fields") is not None:
            campos = set(kwargs["update_fields"])
            if "nome" in campos:
                campos.add("chave_nome")
            kwargs["update_fields"] = campos
        return super().save(*args, **kwargs)

    @property
    def capacidade_formatada(self):
        if self.capacidade is None:
            return ""
        numero = format(self.capacidade.normalize(), "f").replace(".", ",")
        return f"{numero} {self.unidade_capacidade}"

    def __str__(self):
        return self.nome


class MovimentoEstoque(models.Model):
    class Tipo(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SAIDA = "saida", "Saída"

    class Origem(models.TextChoices):
        COMPRA = "compra", "Compra"
        SALDO_INICIAL = "saldo_inicial", "Estoque já existente"
        OUTRA_ENTRADA = "outra_entrada", "Outro recebimento"
        APLICACAO = "aplicacao", "Aplicação no equipamento"
        RETORNO_OS = "retorno_os", "Reutilização após retirada"
        CORRECAO = "correcao", "Correção de lançamento"
        RECUPERACAO_BAIXA = "recuperacao_baixa", "Reaproveitamento de equipamento baixado"

    componente = models.ForeignKey(Componente, on_delete=models.PROTECT, related_name="movimentos")
    tipo = models.CharField(max_length=8, choices=Tipo.choices, default=Tipo.ENTRADA)
    origem = models.CharField(max_length=24, choices=Origem.choices)
    quantidade = models.PositiveIntegerField()
    data = models.DateField(default=timezone.localdate)
    fornecedor = models.ForeignKey("cadastros.Fornecedor", on_delete=models.PROTECT, null=True, blank=True, related_name="movimentos_estoque")
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movimentos_estoque")
    registrado_em = models.DateTimeField(auto_now_add=True)
    observacao = models.TextField(max_length=3000, blank=True)
    chave_confirmacao = models.UUIDField(unique=True, editable=False)
    nome_componente = models.CharField(max_length=160, editable=False)
    nome_fornecedor = models.CharField(max_length=160, blank=True, editable=False)
    nome_tecnico = models.CharField(max_length=320, editable=False)
    intervencao = models.OneToOneField("ativos.IntervencaoComponente", on_delete=models.PROTECT, related_name="movimento_estoque", null=True, blank=True)

    class Meta:
        ordering = ["-data", "-registrado_em", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantidade__gt=0), name="movimento_quantidade_positiva"),
            models.CheckConstraint(condition=models.Q(tipo__in=["entrada", "saida"]), name="movimento_tipo_valido"),
            models.CheckConstraint(condition=models.Q(origem__in=["compra", "saldo_inicial", "outra_entrada", "aplicacao", "retorno_os", "correcao", "recuperacao_baixa"]), name="movimento_origem_valida"),
            models.CheckConstraint(condition=(
                models.Q(tipo="entrada", origem__in=["compra", "saldo_inicial", "outra_entrada"], intervencao__isnull=True)
                | models.Q(tipo="saida", origem="aplicacao", intervencao__isnull=False, fornecedor__isnull=True)
                | models.Q(tipo="entrada", origem__in=["retorno_os", "recuperacao_baixa"], intervencao__isnull=False, fornecedor__isnull=True)
                | models.Q(tipo__in=["entrada", "saida"], origem="correcao", intervencao__isnull=False, fornecedor__isnull=True)
            ), name="movimento_origem_tipo_vinculo"),
        ]

    def clean(self):
        super().clean()
        erros = {}
        if isinstance(self.data, date) and self.data > timezone.localdate():
            erros["data"] = "A entrada deve representar peças já recebidas. A data não pode estar no futuro."
        if erros:
            raise ValidationError(erros)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Movimentações confirmadas não podem ser editadas. A correção exige uma operação própria.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Movimentações confirmadas não podem ser excluídas.")
