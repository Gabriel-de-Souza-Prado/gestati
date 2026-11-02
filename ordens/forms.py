import uuid

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from ativos.models import ComponenteInstalado
from estoque.selectors import componentes_com_saldo
from .models import OrdemServico as OS


class AberturaForm(forms.Form):
    entregue_por = forms.CharField(label="Quem entregou o equipamento", max_length=160)
    problema = forms.CharField(label="Problema informado", max_length=5000, widget=forms.Textarea(attrs={"rows": 5}))
    chave_confirmacao = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class ConfirmacaoForm(forms.Form):
    versao = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    chave_confirmacao = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class AndamentoForm(ConfirmacaoForm):
    status = forms.ChoiceField(label="Nova etapa", choices=[(OS.Status.EM_ATENDIMENTO, "Em atendimento"), (OS.Status.AGUARDANDO_PECA, "Aguardando peça")])
    descricao = forms.CharField(label="Observação do andamento", max_length=5000, widget=forms.Textarea(attrs={"rows": 4}))


class ServicoForm(ConfirmacaoForm):
    descricao = forms.CharField(label="Serviço realizado", max_length=5000, widget=forms.Textarea(attrs={"rows": 5}), help_text="Descreva o trabalho. Se houve troca, instalação ou retirada de peças, registre nas linhas abaixo.")


class EdicaoServicoForm(ServicoForm):
    justificativa = forms.CharField(label="Motivo da edição", max_length=3000, widget=forms.Textarea(attrs={"rows": 3}))


class ConclusaoForm(ConfirmacaoForm):
    resultado = forms.ChoiceField(label="Resultado para o equipamento", choices=OS.Resultado.choices)
    descricao = forms.CharField(label="Parecer da conclusão", max_length=5000, widget=forms.Textarea(attrs={"rows": 5}), help_text="Descreva os testes e o resultado. A OS ficará aguardando coleta; as peças devem ter sido registradas antes.")


class EncerramentoForm(ConfirmacaoForm):
    recebido_por = forms.CharField(label="Quem recebeu o equipamento na devolução", max_length=160)


class BaixaForm(ConfirmacaoForm):
    pass


class ComponenteChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.nome} · estoque: {obj.saldo}" + (" · inativo" if not obj.ativo else "")


class PecaServicoForm(forms.Form):
    componente = ComponenteChoiceField(label="Componente", queryset=componentes_com_saldo().none())
    acao = forms.ChoiceField(label="Ação", choices=[("instalar", "Instalar do estoque"), ("retirar_reutilizar", "Retirar e devolver ao estoque"), ("retirar_sem_retorno", "Retirar sem devolver ao estoque")], initial="instalar")
    quantidade = forms.IntegerField(label="Quantidade", min_value=1, max_value=2147483647, initial=1)

    def __init__(self, *args, ativo_id=None, componentes_permitidos=(), **kwargs):
        super().__init__(*args, **kwargs)
        instalados = ComponenteInstalado.objects.filter(ativo_id=ativo_id).values("componente_id")
        # Subconsulta evita multiplicar o SUM dos movimentos pelo número de
        # equipamentos que usam a mesma especificação.
        self.fields["componente"].queryset = componentes_com_saldo().filter(Q(ativo=True) | Q(pk__in=instalados) | Q(pk__in=componentes_permitidos))


PecasFormSet = forms.formset_factory(PecaServicoForm, extra=2, can_delete=True, max_num=50, validate_max=True, absolute_max=50)


class FiltroOSForm(forms.Form):
    q = forms.CharField(label="Buscar OS", max_length=160, required=False, widget=forms.TextInput(attrs={}))
    status = forms.ChoiceField(label="Etapa", required=False, choices=[("", "Todas"), ("abertas", "Em aberto (inclui coleta)"), *OS.Status.choices])
    inicio = forms.DateField(label="Abertas de", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    fim = forms.DateField(label="Abertas até", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    tecnico = forms.ModelChoiceField(label="Técnico que participou", required=False, queryset=get_user_model().objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tecnico"].queryset = get_user_model().objects.order_by("username")

    def clean(self):
        dados = super().clean()
        if dados.get("inicio") and dados.get("fim") and dados["inicio"] > dados["fim"]:
            raise forms.ValidationError("A data inicial não pode ser posterior à final.")
        return dados
