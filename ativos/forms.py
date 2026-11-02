from copy import deepcopy
from decimal import Decimal
import uuid

from django import forms
from django.db.models import Q

from cadastros.models import CategoriaAtivo, Departamento, Fornecedor
from core.perfis import PerfilConfiguracao as Perfil
from estoque.models import Componente

from .composicao import JA_NO_EQUIPAMENTO, ORIGENS_COMPOSICAO
from .models import Ativo
from .perfis import CAMPOS_PERFIL


class CategoriaSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        if hasattr(value, "instance"):
            option["attrs"]["data-perfil"] = value.instance.perfil_configuracao
        return option


class ComponenteSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        if hasattr(value, "instance"):
            option["attrs"].update({"data-tipo": value.instance.tipo, "data-capacidade": str(value.instance.capacidade or "")})
        return option


class AtivoForm(forms.Form):
    dti = forms.CharField(label="Identificação interna (DTI)", max_length=64, help_text="Código usado para identificar o equipamento.")
    patrimonio = forms.CharField(label="Patrimônio", max_length=64, required=False)
    numero_serie = forms.CharField(label="Número de série", max_length=120, required=False)
    modelo = forms.CharField(label="Modelo", max_length=160, required=False, help_text="Informe quando identificado.")
    categoria = forms.ModelChoiceField(label="Categoria", queryset=CategoriaAtivo.objects.none(), widget=CategoriaSelect)
    departamento = forms.ModelChoiceField(label="Departamento de vínculo", queryset=Departamento.objects.none())
    situacao = forms.ChoiceField(label="Situação", choices=[(Ativo.Situacao.EM_USO, "Em uso"), (Ativo.Situacao.RESERVA, "Em reserva")])
    fornecedor = forms.ModelChoiceField(label="Fornecedor da compra", queryset=Fornecedor.objects.none(), required=False)
    data_aquisicao = forms.DateField(label="Data de aquisição", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    valor_aquisicao = forms.DecimalField(label="Valor de aquisição (R$)", required=False, max_digits=14, decimal_places=2, min_value=0, localize=True)
    garantia = forms.ChoiceField(label="Garantia", choices=[("nao_informada", "Não informada"), ("sem_garantia", "Sem garantia"), ("com_garantia", "Com garantia")], initial=Ativo.Garantia.NAO_INFORMADA)
    inicio_garantia = forms.DateField(label="Início da garantia", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    fim_garantia = forms.DateField(label="Término da garantia", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    observacoes = forms.CharField(label="Observações", required=False, max_length=3000, widget=forms.Textarea(attrs={"rows": 3}))
    chave_confirmacao = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4, required=False)
    versao = forms.IntegerField(widget=forms.HiddenInput, required=False, min_value=1)

    def __init__(self, *args, ativo=None, **kwargs):
        self.ativo = ativo
        super().__init__(*args, **kwargs)
        for nome, modelo in (("categoria", CategoriaAtivo), ("departamento", Departamento), ("fornecedor", Fornecedor)):
            filtro = Q(ativo=True)
            if ativo and getattr(ativo, f"{nome}_id"):
                filtro |= Q(pk=getattr(ativo, f"{nome}_id"))
            self.fields[nome].queryset = modelo.objects.filter(filtro)
        if ativo:
            self.fields["departamento"].disabled = True
            self.fields["departamento"].help_text = "A mudança de vínculo é registrada por transferência."
            self.fields["versao"].required = True
        else:
            self.fields["chave_confirmacao"].required = True

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("inicio_garantia"), dados.get("fim_garantia")
        if dados.get("garantia") == Ativo.Garantia.COM_GARANTIA:
            if not inicio:
                self.add_error("inicio_garantia", "Informe o início da garantia.")
            if not fim:
                self.add_error("fim_garantia", "Informe o término da garantia.")
            elif inicio and fim < inicio:
                self.add_error("fim_garantia", "O término não pode ser anterior ao início.")
        elif inicio or fim:
            self.add_error("garantia", "Selecione Com garantia ou remova as datas.")
        return dados


class EspecificacoesForm(forms.Form):
    def __init__(self, *args, perfil, **kwargs):
        super().__init__(*args, **kwargs)
        for chave, rotulo, tipo in CAMPOS_PERFIL[perfil]:
            if perfil not in (Perfil.COMPUTADOR, Perfil.NOTEBOOK) or chave not in ("hostname", "sistema_operacional"):
                continue
            if tipo == "inteiro":
                campo = forms.IntegerField(min_value=1, max_value=2147483647)
            elif tipo == "decimal":
                campo = forms.DecimalField(min_value=Decimal("0.01"), max_digits=9, decimal_places=2, localize=True)
            elif tipo == "sim_nao":
                campo = forms.ChoiceField(choices=[("", "Não informado"), ("sim", "Sim"), ("nao", "Não")])
            else:
                campo = forms.CharField(max_length=160)
            campo.label, campo.required = rotulo, False
            self.fields[chave] = campo


class ItemComposicaoForm(forms.Form):
    componente = forms.ModelChoiceField(label="Componente", queryset=Componente.objects.none(), widget=ComponenteSelect)
    quantidade = forms.IntegerField(label="Quantidade", min_value=1, max_value=2147483647, initial=1)
    origem = forms.ChoiceField(label="Origem da peça", choices=ORIGENS_COMPOSICAO, initial=JA_NO_EQUIPAMENTO)

    def __init__(self, *args, tipos=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["componente"].queryset = Componente.objects.filter(ativo=True)
        if tipos:
            self.fields["componente"].queryset = self.fields["componente"].queryset.filter(tipo__in=tipos)


class ExtraForm(forms.Form):
    campo = forms.CharField(label="Campo", max_length=80)
    valor = forms.CharField(label="Valor", max_length=500)


ItensFormSet = forms.formset_factory(ItemComposicaoForm, extra=5, can_delete=True, max_num=50, validate_max=True)
ExtrasFormSet = forms.formset_factory(ExtraForm, extra=2, can_delete=True, max_num=30, validate_max=True)


class FiltroAtivoForm(forms.Form):
    q = forms.CharField(label="Buscar ativo", required=False, max_length=160, widget=forms.TextInput())
    departamento = forms.ModelChoiceField(label="Departamento", queryset=Departamento.objects.all(), required=False)
    categoria = forms.ModelChoiceField(label="Categoria", queryset=CategoriaAtivo.objects.all(), required=False)
    situacao = forms.ChoiceField(label="Situação", required=False, choices=[("", "Todas"), *Ativo.Situacao.choices])


GRUPOS_COMPOSICAO = (("processador", "Processador", ["processador"]), ("placa_mae", "Placa-mãe", ["placa_mae"]), ("ram", "Memória RAM", ["ram"]), ("armazenamento", "Armazenamento · SSD / HDD", ["ssd", "hdd"]), ("fonte", "Fonte / alimentação", ["fonte"]), ("outro", "Outros componentes (opcional)", ["outro"]))


def formularios_composicao(post=None):
    grupos=[]
    for codigo, titulo, tipos in GRUPOS_COMPOSICAO:
        fabrica=forms.formset_factory(ItemComposicaoForm, extra=2 if codigo in ("ram", "armazenamento") else 1, can_delete=True, max_num=50, validate_max=True, absolute_max=50)
        grupos.append({"codigo": codigo, "titulo": titulo, "tipos": tipos, "formset": fabrica(post, prefix=f"pecas-{codigo}", form_kwargs={"tipos": tipos})})
    return grupos
