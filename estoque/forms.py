import uuid
from decimal import Decimal

from django import forms
from django.utils import timezone

from cadastros.models import Fornecedor

from .models import Componente, MovimentoEstoque

ORIGENS_ENTRADA = [(valor, rotulo) for valor, rotulo in MovimentoEstoque.Origem.choices if valor in ("compra", "saldo_inicial", "outra_entrada")]


class ComponenteForm(forms.Form):
    nome = forms.CharField(label="Nome do componente", max_length=160, widget=forms.TextInput(attrs={"autofocus": True}))
    tipo = forms.ChoiceField(label="Tipo", choices=[("", "Selecione o tipo"), *Componente.Tipo.choices])
    capacidade = forms.DecimalField(label="Capacidade por unidade", max_digits=9, decimal_places=2, min_value=Decimal("0.01"), required=False, localize=True, help_text="Obrigatória para RAM, SSD e HDD. Ex.: 8 para um pente de 8 GB.")
    unidade_capacidade = forms.ChoiceField(label="Unidade da capacidade", choices=[("", "Não se aplica"), *Componente.UnidadeCapacidade.choices], required=False)
    quantidade_minima = forms.IntegerField(label="Estoque mínimo", min_value=0, max_value=2147483647, initial=0, help_text="O alerta aparece quando o saldo está igual ou abaixo deste valor.")
    descricao = forms.CharField(label="Descrição", max_length=3000, required=False, widget=forms.Textarea(attrs={"rows": 3}))


class FiltroComponenteForm(forms.Form):
    q = forms.CharField(label="Buscar componente", max_length=160, required=False, widget=forms.TextInput(attrs={}))
    tipo = forms.ChoiceField(label="Tipo", required=False, choices=[("", "Todos"), *Componente.Tipo.choices])
    situacao = forms.ChoiceField(label="Situação", required=False, choices=[("", "Todas"), ("ativos", "Ativos"), ("inativos", "Inativos")])
    estoque = forms.ChoiceField(label="Estoque", required=False, choices=[("", "Todos"), ("baixo", "No mínimo ou abaixo"), ("disponivel", "Com saldo")])


class EntradaEstoqueForm(forms.Form):
    componente = forms.ModelChoiceField(label="Componente", queryset=Componente.objects.none())
    quantidade = forms.IntegerField(label="Quantidade recebida", min_value=1, max_value=2147483647)
    origem = forms.ChoiceField(label="Origem", choices=ORIGENS_ENTRADA)
    data = forms.DateField(label="Data do recebimento", initial=timezone.localdate, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    fornecedor = forms.ModelChoiceField(label="Fornecedor", required=False, empty_label="Sem fornecedor informado", queryset=Fornecedor.objects.none(), help_text="Opcional. Registra a procedência do recebimento, sem identificar cada peça física.")
    observacao = forms.CharField(label="Observações", max_length=3000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    chave_confirmacao = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["componente"].queryset = Componente.objects.filter(ativo=True)
        self.fields["fornecedor"].queryset = Fornecedor.objects.filter(ativo=True)


class FiltroMovimentoForm(forms.Form):
    inicio = forms.DateField(label="De", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    fim = forms.DateField(label="Até", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    origem = forms.ChoiceField(label="Origem", required=False, choices=[("", "Todas"), *MovimentoEstoque.Origem.choices])

    def clean(self):
        dados = super().clean()
        if dados.get("inicio") and dados.get("fim") and dados["inicio"] > dados["fim"]:
            raise forms.ValidationError("A data inicial não pode ser posterior à final.")
        return dados
