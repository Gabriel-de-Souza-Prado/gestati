import uuid

from django import forms
from cadastros.models import Departamento


class BaixaForm(forms.Form):
    motivo = forms.CharField(label="Motivo da baixa", max_length=3000, widget=forms.Textarea(attrs={"rows": 4}))
    versao = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    chave_confirmacao = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, instalados, **kwargs):
        super().__init__(*args, **kwargs)
        self.linhas_recuperacao = []
        for linha in instalados:
            chave = f"recuperar_{linha.componente_id}"
            self.fields[chave] = forms.IntegerField(label=f"Recuperar: {linha.componente.nome}", min_value=0,
                                                   max_value=linha.quantidade, required=False, initial=0)
            self.linhas_recuperacao.append({"linha": linha, "campo": self[chave]})

    def itens(self):
        return [{"componente_id": item["linha"].componente_id, "quantidade": self.cleaned_data[item["campo"].name]}
                for item in self.linhas_recuperacao if self.cleaned_data.get(item["campo"].name)]


class FiltroBaixaForm(forms.Form):
    q = forms.CharField(label="Buscar baixas", required=False, max_length=160,
                        widget=forms.TextInput(attrs={}))
    inicio = forms.DateField(label="Registradas de", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    fim = forms.DateField(label="Registradas até", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    departamento = forms.ModelChoiceField(label="Departamento na baixa", queryset=Departamento.objects.all(), required=False)

    def clean(self):
        dados = super().clean()
        if dados.get("inicio") and dados.get("fim") and dados["inicio"] > dados["fim"]:
            raise forms.ValidationError("A data inicial não pode ser posterior à final.")
        return dados
