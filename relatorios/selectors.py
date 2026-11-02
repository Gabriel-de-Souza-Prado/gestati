"""Consultas somente leitura: reutilizam filtros e saldos dos módulos de origem."""
from django.db.models import Exists, OuterRef, Prefetch
from ativos.models import Ativo
from ativos.selectors import ativos_para_consulta, filtrar_busca_ativos
from baixas.selectors import baixas_para_consulta
from core.normalizacao import normalizar_identificador
from estoque.selectors import componentes_com_saldo
from movimentacoes.models import EmprestimoAtivo, TransferenciaAtivo
from movimentacoes.selectors import filtrar_movimentacoes
from ordens.models import RegistroAtendimento, RevisaoServico
from .definicoes import RELATORIOS
from ordens.selectors import filtrar_ordens, ordens_para_consulta


def consultar(tipo, dados):
    if tipo not in RELATORIOS:
        raise ValueError("Relatório não encontrado.")
    if tipo == "ativos":
        consulta = filtrar_busca_ativos(ativos_para_consulta(), dados.get("q", ""))
        for campo in ("categoria", "departamento", "situacao"):
            if dados.get(campo): consulta = consulta.filter(**{campo: dados[campo]})
        if dados.get("emprestado"):
            consulta = consulta.annotate(emprestado=Exists(EmprestimoAtivo.objects.filter(ativo_id=OuterRef("pk"), encerrado_em__isnull=True)))
            consulta = consulta.filter(emprestado=dados["emprestado"] == "sim")
        return consulta
    if tipo == "ordens":
        consulta = filtrar_ordens(ordens_para_consulta(), dados).prefetch_related(Prefetch("registros", queryset=RegistroAtendimento.objects.only("id", "ordem_id", "nome_tecnico", "registrado_em")), Prefetch("registros__revisoes", queryset=RevisaoServico.objects.only("id", "registro_id", "nome_tecnico", "registrado_em")))
        if dados.get("departamento"): consulta = consulta.filter(departamento=dados["departamento"])
        return consulta
    if tipo == "estoque":
        # Catálogo usado só na composição não é estoque físico disponível.
        consulta = componentes_com_saldo().filter(acompanhar_estoque=True)
        if dados.get("q"):
            consulta = consulta.filter(chave_nome__contains=normalizar_identificador(dados["q"]))
        if dados.get("tipo"): consulta = consulta.filter(tipo=dados["tipo"])
        if dados.get("situacao"): consulta = consulta.filter(ativo=dados["situacao"] == "ativos")
        if dados.get("baixo"): consulta = consulta.filter(estoque_baixo=True)
        return consulta
    if tipo == "baixas": return baixas_para_consulta(dados)
    modelo = EmprestimoAtivo if tipo == "emprestimos" else TransferenciaAtivo
    return filtrar_movimentacoes(modelo.objects.select_related("ativo"), dados)


def pendencias_operacionais():
    """Contagens sem duplicar ativo por histórico, com atalhos para as consultas."""
    from ordens.models import OrdemServico
    return {
        "os_abertas": OrdemServico.objects.exclude(status=OrdemServico.Status.ENCERRADA).count(),
        "aguardando_coleta": OrdemServico.objects.filter(status="aguardando_coleta").count(),
        "aguardando_peca": OrdemServico.objects.filter(status="aguardando_peca").count(),
        "emprestimos_abertos": EmprestimoAtivo.objects.filter(encerrado_em__isnull=True).count(),
        "estoque_baixo": componentes_com_saldo().filter(acompanhar_estoque=True, estoque_baixo=True).count(),
    }
