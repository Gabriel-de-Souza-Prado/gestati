from django.core.exceptions import ValidationError
from django.db import models

from core.normalizacao import normalizar_identificador, padronizar_espacos
from core.perfis import PerfilConfiguracao

from .validators import normalizar_cnpj


class Departamento(models.Model):
    nome = models.CharField("nome", max_length=160)
    sigla = models.CharField("sigla", max_length=24, blank=True)
    ativo = models.BooleanField("ativo", default=True)
    chave_nome = models.CharField(
        max_length=320,
        unique=True,
        editable=False,
        blank=True,
        error_messages={"unique": "Já existe um departamento com esse nome."},
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chave_nome", "pk"]
        verbose_name = "departamento"
        verbose_name_plural = "departamentos"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(chave_nome=""), name="departamento_nome_nao_vazio"
            ),
        ]

    def preparar_identificacao(self):
        self.nome = padronizar_espacos(self.nome)
        self.sigla = padronizar_espacos(self.sigla).upper()
        self.chave_nome = normalizar_identificador(self.nome)

    def clean(self):
        super().clean()
        self.preparar_identificacao()
        if not self.chave_nome:
            raise ValidationError({"nome": "Informe o nome do departamento."})

    def save(self, *args, **kwargs):
        self.preparar_identificacao()
        if kwargs.get("update_fields") is not None:
            campos = set(kwargs["update_fields"])
            if "nome" in campos:
                campos.add("chave_nome")
            kwargs["update_fields"] = campos
        return super().save(*args, **kwargs)

    @property
    def nome_exibicao(self):
        return self.nome if self.ativo else f"{self.nome} (Inativado)"

    def __str__(self):
        return self.nome_exibicao


class CategoriaAtivo(models.Model):
    nome = models.CharField("nome", max_length=160)
    perfil_configuracao = models.CharField("perfil de cadastro", max_length=16, choices=PerfilConfiguracao.choices, default=PerfilConfiguracao.GENERICO)
    ativo = models.BooleanField("ativa", default=True)
    chave_nome = models.CharField(
        max_length=320, unique=True, editable=False, blank=True,
        error_messages={"unique": "Já existe uma categoria com esse nome, inclusive entre as inativas."},
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chave_nome", "pk"]
        verbose_name = "categoria de equipamento"
        verbose_name_plural = "categorias de equipamentos"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(chave_nome=""), name="categoria_ativo_nome_nao_vazio"
            ),
        ]

    def preparar_identificacao(self):
        self.nome = padronizar_espacos(self.nome)
        self.chave_nome = normalizar_identificador(self.nome)

    def clean(self):
        super().clean()
        self.preparar_identificacao()
        if not self.chave_nome:
            raise ValidationError({"nome": "Informe o nome da categoria."})

    def save(self, *args, **kwargs):
        self.preparar_identificacao()
        if kwargs.get("update_fields") is not None:
            campos = set(kwargs["update_fields"])
            if "nome" in campos:
                campos.add("chave_nome")
            kwargs["update_fields"] = campos
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


class IdentificadorDepartamento(models.Model):
    """Índice interno que impede colisão entre nome e sigla de departamentos."""

    departamento = models.ForeignKey(
        Departamento, on_delete=models.CASCADE, related_name="identificadores"
    )
    chave = models.CharField(max_length=320, unique=True)

    class Meta:
        verbose_name = "identificador de departamento"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(chave=""), name="identificador_departamento_nao_vazio"
            ),
        ]


class Fornecedor(models.Model):
    nome = models.CharField("nome", max_length=160)
    cnpj = models.CharField(
        "CNPJ", max_length=14, blank=True, null=True, unique=True,
        error_messages={"unique": "Já existe um fornecedor com esse CNPJ, inclusive entre os inativos."},
    )
    telefone = models.CharField("telefone", max_length=40, blank=True)
    email = models.EmailField("e-mail", blank=True)
    ativo = models.BooleanField("ativo", default=True)
    chave_nome = models.CharField(max_length=320, db_index=True, editable=False, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chave_nome", "pk"]
        verbose_name = "fornecedor"
        verbose_name_plural = "fornecedores"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(chave_nome=""), name="fornecedor_nome_nao_vazio"
            ),
            models.CheckConstraint(
                condition=models.Q(cnpj__isnull=True) | models.Q(cnpj__regex=r"^[A-Z0-9]{12}[0-9]{2}$"),
                name="fornecedor_cnpj_formato",
            ),
        ]

    def preparar_identificacao(self):
        self.nome = padronizar_espacos(self.nome)
        self.chave_nome = normalizar_identificador(self.nome)
        self.telefone = padronizar_espacos(self.telefone)
        self.email = (self.email or "").strip()
        try:
            self.cnpj = normalizar_cnpj(self.cnpj)
        except ValidationError as erro:
            raise ValidationError({"cnpj": erro.messages}) from None

    def clean(self):
        super().clean()
        self.preparar_identificacao()
        if not self.chave_nome:
            raise ValidationError({"nome": "Informe o nome do fornecedor."})

    def save(self, *args, **kwargs):
        self.preparar_identificacao()
        if kwargs.get("update_fields") is not None:
            campos = set(kwargs["update_fields"])
            if "nome" in campos:
                campos.add("chave_nome")
            kwargs["update_fields"] = campos
        return super().save(*args, **kwargs)

    @property
    def cnpj_formatado(self):
        if not self.cnpj:
            return ""
        c = self.cnpj
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"

    def __str__(self):
        return self.nome
