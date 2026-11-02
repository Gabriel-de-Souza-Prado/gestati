from django.db.models import Q


def filtrar_movimentacoes(consulta, dados):
    termo = dados.get("q", "").strip()
    if termo:
        consulta = consulta.filter(
            Q(dti_ativo__icontains=termo) | Q(patrimonio_ativo__icontains=termo) | Q(serie_ativo__icontains=termo)
            | Q(descricao_ativo__icontains=termo) | Q(ativo__dti__icontains=termo)
            | Q(ativo__patrimonio__icontains=termo) | Q(ativo__numero_serie__icontains=termo)
            | Q(ativo__especificacoes__hostname__icontains=termo) | Q(ativo__modelo__icontains=termo))
    if dados.get("inicio"):
        consulta = consulta.filter(registrado_em__date__gte=dados["inicio"])
    if dados.get("fim"):
        consulta = consulta.filter(registrado_em__date__lte=dados["fim"])
    if dados.get("destino"):
        consulta = consulta.filter(destino=dados["destino"])
    if dados.get("situacao") == "abertos":
        consulta = consulta.filter(encerrado_em__isnull=True)
    elif dados.get("situacao") == "devolvidos":
        consulta = consulta.filter(encerramento="devolucao")
    elif dados.get("situacao") == "transferidos":
        consulta = consulta.filter(encerramento="transferencia")
    elif dados.get("situacao") == "baixados":
        consulta = consulta.filter(encerramento="baixa")
    return consulta
