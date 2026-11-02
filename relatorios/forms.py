from datetime import date

from django import forms
from ativos.forms import FiltroAtivoForm
from baixas.forms import FiltroBaixaForm
from cadastros.models import Departamento
from movimentacoes.forms import FiltroMovimentacaoForm
from ordens.forms import FiltroOSForm
from estoque.models import Componente


class FiltroAtivos(FiltroAtivoForm):
    emprestado = forms.ChoiceField(label="Empréstimo", required=False,
        choices=[("", "Todos"), ("sim", "Somente emprestados"), ("nao", "Sem empréstimo aberto")])


class FiltroOrdens(FiltroOSForm):
    departamento = forms.ModelChoiceField(label="Departamento na abertura", required=False, queryset=Departamento.objects.all())


class FiltroEstoque(forms.Form):
    q = forms.CharField(label="Buscar componente", required=False, max_length=160)
    tipo = forms.ChoiceField(label="Tipo", required=False, choices=[("", "Todos"), *Componente.Tipo.choices])
    situacao = forms.ChoiceField(label="Cadastro", required=False,
        choices=[("", "Ativos e inativos"), ("ativos", "Ativos"), ("inativos", "Inativos")])
    baixo = forms.BooleanField(label="Somente estoque baixo", required=False)


def formulario(tipo, dados):
    if tipo == "ativos": return FiltroAtivos(dados)
    if tipo == "ordens": return FiltroOrdens(dados)
    if tipo == "estoque": return FiltroEstoque(dados)
    if tipo == "baixas": return FiltroBaixaForm(dados)
    return FiltroMovimentacaoForm(dados, emprestimos=tipo == "emprestimos")


def descrever_filtros(form):
    """Rótulos validados, iguais na tela e no PDF; nenhum HTML é aceito aqui."""
    filtros = []
    for nome, campo in form.fields.items():
        valor = form.cleaned_data.get(nome)
        if valor is None or valor == "" or valor is False:
            continue
        if isinstance(valor, date): texto = valor.strftime("%d/%m/%Y")
        elif valor is True: texto = "Sim"
        elif isinstance(campo, forms.ModelChoiceField): texto = str(valor)
        elif isinstance(campo, forms.ChoiceField): texto = str(dict(campo.choices).get(valor, valor))
        else: texto = str(valor)
        filtros.append(f"{campo.label}: {texto}")
    return filtros
