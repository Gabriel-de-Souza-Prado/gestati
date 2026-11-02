from django.db.models import Q

from .models import OrdemServico as OS


def ordens_para_consulta():
    return OS.objects.select_related("ativo", "aberto_por")


def filtrar_ordens(consulta, dados):
    termo = dados.get("q", "").strip()
    if termo:
        busca = (Q(dti_ativo__icontains=termo) | Q(patrimonio_ativo__icontains=termo)
                 | Q(serie_ativo__icontains=termo) | Q(nome_ativo__icontains=termo)
                 | Q(ativo__dti__icontains=termo) | Q(ativo__patrimonio__icontains=termo)
                 | Q(ativo__numero_serie__icontains=termo) | Q(modelo_ativo__icontains=termo)
                 | Q(ativo__modelo__icontains=termo) | Q(ativo__especificacoes__hostname__icontains=termo))
        if termo.isascii() and termo.isdigit() and len(termo) < 19:
            busca |= Q(pk=int(termo))
        consulta = consulta.filter(busca)
    status = dados.get("status")
    if status == "abertas":
        consulta = consulta.exclude(status=OS.Status.ENCERRADA)
    elif status:
        consulta = consulta.filter(status=status)
    if dados.get("inicio"):
        consulta = consulta.filter(aberto_em__date__gte=dados["inicio"])
    if dados.get("fim"):
        consulta = consulta.filter(aberto_em__date__lte=dados["fim"])
    if dados.get("tecnico"):
        consulta = consulta.filter(Q(aberto_por=dados["tecnico"]) | Q(registros__tecnico=dados["tecnico"]) | Q(registros__revisoes__tecnico=dados["tecnico"])).distinct()
    return consulta


ROTULOS_PECAS = {"instalar": "Instalado do estoque", "retirar_reutilizar": "Retirado e devolvido ao estoque", "retirar_sem_retorno": "Retirado sem retorno ao estoque"}


def registros_para_apresentacao(ordem):
    registros = list(ordem.registros.prefetch_related("intervencoes", "revisoes"))
    for registro in registros:
        revisoes = list(registro.revisoes.all())
        registro.revisao_atual = revisoes[0] if revisoes else None
        registro.descricao_exibicao = registro.revisao_atual.descricao if revisoes else registro.descricao
        nomes = {i.componente_id: i.nome_componente for i in registro.intervencoes.all()}
        iniciais = registro.dados_confirmacao.get("dados", {}).get("itens", [])
        registro.pecas_iniciais = [{**i, "nome": nomes.get(i["componente_id"], "Componente"), "rotulo": ROTULOS_PECAS[i["acao"]]} for i in iniciais]
        atuais = registro.revisao_atual.itens if revisoes else registro.pecas_iniciais
        registro.pecas_exibicao = [{**i, "rotulo": ROTULOS_PECAS[i["acao"]]} for i in atuais]
    return registros
