from django import forms

from .validators import normalizar_cnpj
from core.perfis import PerfilConfiguracao


class DepartamentoForm(forms.Form):
    nome = forms.CharField(
        label="Nome do departamento",
        max_length=160,
        widget=forms.TextInput(attrs={"autofocus": True}),
    )
    sigla = forms.CharField(
        label="Sigla",
        max_length=24,
        required=False,
    )


class FiltroDepartamentoForm(forms.Form):
    q = forms.CharField(
        label="Buscar departamento",
        max_length=160,
        required=False,
        widget=forms.TextInput(attrs={}),
    )
    situacao = forms.ChoiceField(
        label="Situação",
        required=False,
        choices=[("", "Todas"), ("ativos", "Ativos"), ("inativos", "Inativos")],
    )


class SituacaoCadastroForm(forms.Form):
    ativo = forms.TypedChoiceField(
        choices=[("1", "Ativar"), ("0", "Inativar")], coerce=lambda valor: valor == "1"
    )


class CategoriaAtivoForm(forms.Form):
    nome = forms.CharField(
        label="Nome da categoria", max_length=160,
        help_text="Ex.: Computador, Monitor, Nobreak ou outro tipo de equipamento.",
        widget=forms.TextInput(attrs={"autofocus": True}),
    )
    perfil_configuracao = forms.ChoiceField(
        label="Perfil de cadastro", choices=PerfilConfiguracao.choices,
        initial=PerfilConfiguracao.GENERICO, required=False,
        help_text="Computador e notebook possuem nome na rede e componentes. Para os demais, use Dados básicos e Observações.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        escolhas = [("generico", "Dados básicos"), ("computador", "Computador"), ("notebook", "Notebook")]
        atual = self.initial.get("perfil_configuracao")
        if atual and atual not in {c for c, _ in escolhas}:
            escolhas.append((atual, "Dados básicos (categoria existente)"))
        self.fields["perfil_configuracao"].choices = escolhas

    def clean_perfil_configuracao(self):
        return self.cleaned_data["perfil_configuracao"] or None


class FiltroCategoriaForm(forms.Form):
    q = forms.CharField(
        label="Buscar categoria", max_length=160, required=False,
        widget=forms.TextInput(attrs={}),
    )
    situacao = forms.ChoiceField(
        label="Situação", required=False,
        choices=[("", "Todas"), ("ativas", "Ativas"), ("inativas", "Inativas")],
    )


class FornecedorForm(forms.Form):
    nome = forms.CharField(
        label="Nome do fornecedor", max_length=160,
        widget=forms.TextInput(attrs={"autofocus": True}),
    )
    cnpj = forms.CharField(
        label="CNPJ", max_length=18, required=False,
        help_text="Com ou sem pontuação. Aceita CNPJ numérico e alfanumérico.",
    )
    telefone = forms.CharField(label="Telefone", max_length=40, required=False)
    email = forms.EmailField(label="E-mail", max_length=254, required=False)

    def clean_cnpj(self):
        return normalizar_cnpj(self.cleaned_data["cnpj"])


class FiltroFornecedorForm(forms.Form):
    q = forms.CharField(
        label="Buscar fornecedor", max_length=160, required=False,
        widget=forms.TextInput(attrs={}),
    )
    situacao = forms.ChoiceField(
        label="Situação", required=False,
        choices=[("", "Todas"), ("ativos", "Ativos"), ("inativos", "Inativos")],
    )

