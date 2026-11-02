import uuid
from django import forms
from django.utils import timezone
from estoque.models import Componente
from estoque.forms import ComponenteForm
from .models import IntervencaoComponente


class EspecificacaoRapidaForm(ComponenteForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("quantidade_minima",):
            self.fields.pop(campo)


class AlteracaoForm(forms.Form):
    tipo = forms.ChoiceField(label="O que aconteceu?", choices=[("fisica", "Troca ou upgrade físico sem OS"), ("correcao", "Corrigir um cadastro errado")])
    justificativa = forms.CharField(label="Justificativa", max_length=3000, widget=forms.Textarea(attrs={"rows": 3}))
    intervencao = forms.ModelChoiceField(label="Lançamento de inclusão que estava errado", queryset=IntervencaoComponente.objects.none(), required=False)
    componente = forms.ModelChoiceField(label="Especificação correta", queryset=Componente.objects.filter(ativo=True), required=False)
    quantidade = forms.IntegerField(label="Quantidade correta desse lançamento", required=False, min_value=0, max_value=2147483647, help_text="Zero remove uma inclusão indevida. A correção substitui integralmente o lançamento escolhido.")
    versao = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    chave_confirmacao = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, ativo_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["intervencao"].queryset = IntervencaoComponente.objects.filter(ativo_id=ativo_id, revisao_os__isnull=True, origem__in=["estoque", "no_equipamento", "ajuste_adicao"], correcao_configuracao__isnull=True)
        self.fields["intervencao"].label_from_instance = lambda i: f"#{i.pk} · {i.quantidade} × {i.nome_componente} · {timezone.localtime(i.registrado_em):%d/%m/%Y %H:%M}"

    def clean(self):
        dados=super().clean()
        if dados.get("tipo") == "correcao":
            if not dados.get("intervencao"):
                self.add_error("intervencao", "Selecione o lançamento original.")
            if dados.get("quantidade") is None:
                self.add_error("quantidade", "Informe a quantidade correta.")
            elif dados["quantidade"] and not dados.get("componente"):
                self.add_error("componente", "Selecione a especificação correta.")
        return dados
