from django.db.models import Case, IntegerField, Prefetch, Q, Value, When

from core.normalizacao import normalizar_identificador, padronizar_espacos
from .models import Ativo, ComponenteInstalado


def componentes_instalados_para_consulta(ativo):
    ordem = ("processador", "placa_mae", "ram", "ssd", "hdd", "fonte")
    return ativo.componentes_instalados.select_related("componente").annotate(
        ordem_tipo=Case(*[When(componente__tipo=tipo, then=Value(i)) for i, tipo in enumerate(ordem)],
            default=Value(len(ordem)), output_field=IntegerField())).order_by("ordem_tipo", "componente__chave_nome", "pk")


def ativos_para_consulta():
    from movimentacoes.models import EmprestimoAtivo
    return Ativo.objects.select_related("categoria", "departamento", "fornecedor", "criado_por").prefetch_related(Prefetch("emprestimos", queryset=EmprestimoAtivo.objects.filter(encerrado_em__isnull=True), to_attr="emprestimos_em_aberto"))


def filtrar_busca_ativos(consulta, termo, identificador=""):
    termo = termo.strip()
    if not termo:
        return consulta
    if identificador == "dti":
        return consulta.filter(dti=termo.upper())
    if identificador == "patrimonio":
        return consulta.filter(patrimonio=padronizar_espacos(termo).upper())
    if identificador == "serie":
        return consulta.filter(numero_serie__iexact=padronizar_espacos(termo))
    return consulta.filter(Q(dti__icontains=termo) | Q(patrimonio__icontains=termo) | Q(numero_serie__icontains=termo) | Q(chave_nome__contains=normalizar_identificador(termo)) | Q(modelo__icontains=termo) | Q(especificacoes__hostname__icontains=termo)).annotate(prioridade_busca=Case(When(Q(dti__iexact=termo) | Q(patrimonio__iexact=padronizar_espacos(termo)), then=Value(0)), default=Value(1), output_field=IntegerField())).order_by("prioridade_busca", "chave_nome", "pk")
