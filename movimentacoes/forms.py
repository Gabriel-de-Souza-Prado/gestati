import uuid

from django import forms
from cadastros.models import Departamento


class MovimentacaoForm(forms.Form):
    destino = forms.ModelChoiceField(label="Departamento de destino", queryset=Departamento.objects.filter(ativo=True))
    motivo = forms.CharField(label="Motivo", max_length=3000, widget=forms.Textarea(attrs={"rows": 4}))
    versao = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    chave_confirmacao = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class EmprestimoForm(MovimentacaoForm):
    recebido_por = forms.CharField(label="Quem recebeu o equipamento emprestado", max_length=160)


class DevolucaoForm(forms.Form):
    devolvido_por = forms.CharField(label="Quem devolveu o equipamento", max_length=160)
    observacoes = forms.CharField(label="Observações da devolução", required=False, max_length=3000, widget=forms.Textarea(attrs={"rows": 3}))
    versao = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    chave_confirmacao = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class FiltroMovimentacaoForm(forms.Form):
    q = forms.CharField(label="Buscar transferências", max_length=160, required=False, widget=forms.TextInput(attrs={}))
    inicio = forms.DateField(label="Registradas de", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    fim = forms.DateField(label="Registradas até", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    destino = forms.ModelChoiceField(label="Destino", queryset=Departamento.objects.all(), required=False)
    situacao = forms.ChoiceField(label="Empréstimos", choices=[("", "Todos"), ("abertos", "Em aberto"), ("devolvidos", "Devolvidos"), ("transferidos", "Encerrados por transferência"), ("baixados", "Encerrados por baixa")], required=False)

    def __init__(self, *args, emprestimos=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].label = "Buscar empréstimos" if emprestimos else "Buscar transferências"
        if not emprestimos:
            self.fields.pop("situacao")

    def clean(self):
        dados = super().clean()
        if dados.get("inicio") and dados.get("fim") and dados["inicio"] > dados["fim"]:
            raise forms.ValidationError("A data inicial não pode ser posterior à final.")
        return dados
