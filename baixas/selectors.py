from django.db.models import Q
from .models import BaixaAtivo


def baixas_para_consulta(dados):
    registros = BaixaAtivo.objects.select_related("ativo", "ordem")
    q = dados.get("q", "").strip()
    if q:
        registros = registros.filter(Q(dti_ativo__icontains=q) | Q(patrimonio_ativo__icontains=q)
            | Q(serie_ativo__icontains=q) | Q(descricao_ativo__icontains=q)
            | Q(ativo__dti__icontains=q) | Q(ativo__patrimonio__icontains=q)
            | Q(ativo__numero_serie__icontains=q) | Q(ativo__modelo__icontains=q)
            | Q(ativo__especificacoes__hostname__icontains=q))
    if dados.get("inicio"):
        registros = registros.filter(registrado_em__date__gte=dados["inicio"])
    if dados.get("fim"):
        registros = registros.filter(registrado_em__date__lte=dados["fim"])
    if dados.get("departamento"):
        registros = registros.filter(departamento=dados["departamento"])
    return registros
