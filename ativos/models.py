import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.normalizacao import normalizar_identificador, padronizar_espacos


class Ativo(models.Model):
    class Situacao(models.TextChoices):
        EM_USO = "em_uso", "Em uso"
        RESERVA = "reserva", "Em reserva"
        EM_MANUTENCAO = "em_manutencao", "Em manutenção"
        SEM_REPARO = "sem_reparo", "Sem reparo"
        BAIXADO = "baixado", "Baixado"

    class Garantia(models.TextChoices):
        NAO_INFORMADA = "nao_informada", "Não informada"
        SEM_GARANTIA = "sem_garantia", "Sem garantia"
        COM_GARANTIA = "com_garantia", "Com garantia informada"

    dti = models.CharField("DTI", max_length=64, unique=True, error_messages={"unique": "Já existe um ativo com esse DTI."})
    patrimonio = models.CharField("patrimônio", max_length=64, unique=True, null=True, blank=True, error_messages={"unique": "Já existe um ativo com esse patrimônio."})
    numero_serie = models.CharField("número de série", max_length=120, blank=True, db_index=True)
    nome = models.CharField("nome do equipamento", max_length=160)
    modelo = models.CharField("modelo", max_length=160, blank=True)
    categoria = models.ForeignKey("cadastros.CategoriaAtivo", on_delete=models.PROTECT, related_name="ativos")
    departamento = models.ForeignKey("cadastros.Departamento", on_delete=models.PROTECT, related_name="ativos")
    fornecedor = models.ForeignKey("cadastros.Fornecedor", on_delete=models.PROTECT, related_name="ativos", null=True, blank=True)
    data_aquisicao = models.DateField(null=True, blank=True)
    valor_aquisicao = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    garantia = models.CharField(max_length=16, choices=Garantia.choices, default=Garantia.NAO_INFORMADA)
    inicio_garantia = models.DateField(null=True, blank=True)
    fim_garantia = models.DateField(null=True, blank=True)
    situacao = models.CharField(max_length=16, choices=Situacao.choices, default=Situacao.EM_USO)
    especificacoes = models.JSONField(default=dict, blank=True)
    extras = models.JSONField(default=list, blank=True)
    observacoes = models.TextField(max_length=3000, blank=True)
    chave_nome = models.CharField(max_length=320, editable=False, db_index=True)
    chave_cadastro = models.UUIDField(unique=True, editable=False)
    dados_cadastro = models.JSONField(editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ativos_cadastrados")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    versao = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["chave_nome", "pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(dti__regex=r"^[A-Z0-9-]+$") & models.Q(dti__regex=r"[A-Z0-9]"), name="ativo_dti_formato"),
            models.CheckConstraint(condition=~models.Q(chave_nome=""), name="ativo_nome_nao_vazio"),
            models.CheckConstraint(condition=models.Q(patrimonio__isnull=True) | ~models.Q(patrimonio=""), name="ativo_patrimonio_nao_vazio"),
            models.CheckConstraint(condition=models.Q(valor_aquisicao__isnull=True) | models.Q(valor_aquisicao__gte=0), name="ativo_valor_nao_negativo"),
            models.CheckConstraint(condition=(models.Q(garantia="com_garantia", inicio_garantia__isnull=False, fim_garantia__isnull=False, fim_garantia__gte=models.F("inicio_garantia")) | models.Q(garantia__in=["nao_informada", "sem_garantia"], inicio_garantia__isnull=True, fim_garantia__isnull=True)), name="ativo_garantia_coerente"),
        ]

    def preparar_identificacao(self):
        self.dti = str(self.dti or "").strip()
        if self.dti.isascii():
            self.dti = self.dti.upper()
        self.patrimonio = padronizar_espacos(self.patrimonio).upper() or None
        self.numero_serie = padronizar_espacos(self.numero_serie)
        self.nome = padronizar_espacos(self.nome)
        self.modelo = padronizar_espacos(self.modelo)
        self.chave_nome = normalizar_identificador(self.nome)
        self.observacoes = (self.observacoes or "").strip()

    def clean(self):
        super().clean()
        self.preparar_identificacao()
        erros = {}
        if not re.fullmatch(r"(?=.*[A-Z0-9])[A-Z0-9-]+", self.dti):
            erros["dti"] = "Informe o DTI da etiqueta usando letras, números e hífens. Os zeros iniciais são preservados."
        if not self.nome:
            erros["nome"] = "Informe o nome do equipamento."
        if self.garantia == self.Garantia.COM_GARANTIA:
            if not self.inicio_garantia:
                erros["inicio_garantia"] = "Informe o início da garantia."
            if not self.fim_garantia:
                erros["fim_garantia"] = "Informe o término da garantia."
        elif self.inicio_garantia or self.fim_garantia:
            erros["garantia"] = "Selecione Com garantia informada para registrar as datas da garantia."
        if erros:
            raise ValidationError(erros)

    def save(self, *args, **kwargs):
        self.preparar_identificacao()
        return super().save(*args, **kwargs)

    def esta_em_garantia(self, em=None):
        em = em or timezone.localdate()
        return bool(self.garantia == self.Garantia.COM_GARANTIA and self.inicio_garantia and self.fim_garantia and self.inicio_garantia <= em <= self.fim_garantia)

    def __str__(self):
        return f"{self.dti} — {self.nome}"

    @property
    def descricao(self):
        return f"{self.categoria.nome} {self.modelo}".strip()


class ComponenteInstalado(models.Model):
    ativo = models.ForeignKey(Ativo, on_delete=models.PROTECT, related_name="componentes_instalados")
    componente = models.ForeignKey("estoque.Componente", on_delete=models.PROTECT, related_name="instalacoes")
    quantidade = models.PositiveIntegerField()

    class Meta:
        ordering = ["componente__chave_nome", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["ativo", "componente"], name="instalado_ativo_componente_unico"),
            models.CheckConstraint(condition=models.Q(quantidade__gt=0), name="instalado_quantidade_positiva"),
        ]


class IntervencaoComponente(models.Model):
    ativo = models.ForeignKey(Ativo, on_delete=models.PROTECT, related_name="intervencoes")
    componente = models.ForeignKey("estoque.Componente", on_delete=models.PROTECT, related_name="intervencoes")
    quantidade = models.PositiveIntegerField()
    operacao = models.UUIDField()
    origem = models.CharField(max_length=16, choices=[("no_equipamento", "Já veio no equipamento"), ("estoque", "Estoque da TI"), ("retorno_estoque", "Retirada para reutilização"), ("sem_retorno", "Retirada sem retorno ao estoque"), ("ajuste_adicao", "Configuração corrigida: inclusão"), ("ajuste_retirada", "Configuração corrigida: retirada"), ("ajuste_estoque", "Correção do estoque na edição do serviço")])
    registro_os = models.ForeignKey("ordens.RegistroAtendimento", on_delete=models.PROTECT, related_name="intervencoes", null=True, blank=True)
    alteracao = models.ForeignKey("AlteracaoConfiguracao", on_delete=models.PROTECT, related_name="intervencoes", null=True, blank=True)
    revisao_os = models.ForeignKey("ordens.RevisaoServico", on_delete=models.PROTECT, related_name="intervencoes", null=True, blank=True)
    baixa = models.ForeignKey("baixas.BaixaAtivo", on_delete=models.PROTECT, related_name="intervencoes", null=True, blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrado_em = models.DateTimeField(auto_now_add=True)
    nome_componente = models.CharField(max_length=160)
    dti_ativo = models.CharField(max_length=64)

    class Meta:
        ordering = ["registrado_em", "pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantidade__gt=0), name="intervencao_quantidade_positiva"),
            models.CheckConstraint(condition=(models.Q(revisao_os__isnull=True) & (models.Q(registro_os__isnull=True, alteracao__isnull=True, baixa__isnull=True, origem__in=["no_equipamento", "estoque"]) | models.Q(registro_os__isnull=False, alteracao__isnull=True, baixa__isnull=True, origem__in=["estoque", "retorno_estoque", "sem_retorno"]) | models.Q(registro_os__isnull=True, alteracao__isnull=False, baixa__isnull=True, origem__in=["estoque", "retorno_estoque", "sem_retorno", "ajuste_adicao", "ajuste_retirada"]) | models.Q(registro_os__isnull=True, alteracao__isnull=True, baixa__isnull=False, origem="retorno_estoque"))) | models.Q(revisao_os__isnull=False, registro_os__isnull=True, alteracao__isnull=True, baixa__isnull=True, origem__in=["ajuste_adicao", "ajuste_retirada", "ajuste_estoque"]), name="intervencao_origem_valida"),
            models.UniqueConstraint(fields=["operacao", "componente", "origem"], name="intervencao_operacao_peca_origem"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("O registro de composição não pode ser sobrescrito.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("O registro de composição deve ser preservado.")


class AlteracaoConfiguracao(models.Model):
    ativo = models.ForeignKey(Ativo, on_delete=models.PROTECT, related_name="alteracoes_configuracao")
    tipo = models.CharField(max_length=12, choices=[("fisica", "Troca/upgrade físico sem OS"), ("correcao", "Correção de cadastro")])
    justificativa = models.TextField(max_length=3000)
    tecnico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    nome_tecnico = models.CharField(max_length=320)
    registrado_em = models.DateTimeField(auto_now_add=True)
    chave_confirmacao = models.UUIDField(unique=True, editable=False)
    dados_confirmacao = models.JSONField(editable=False)
    antes = models.JSONField(editable=False)
    depois = models.JSONField(editable=False)
    efeitos_estoque = models.JSONField(default=list, blank=True, editable=False)
    intervencao_corrigida = models.OneToOneField(IntervencaoComponente, on_delete=models.PROTECT, null=True, blank=True, related_name="correcao_configuracao")

    class Meta:
        ordering = ["-registrado_em", "-pk"]
        constraints = [models.CheckConstraint(condition=models.Q(tipo="fisica", intervencao_corrigida__isnull=True) | models.Q(tipo="correcao", intervencao_corrigida__isnull=False), name="alteracao_tipo_origem_coerentes")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("A alteração confirmada deve ser preservada.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("O histórico da configuração deve ser preservado.")
