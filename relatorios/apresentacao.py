"""Uma representação das linhas para HTML/PDF, sem alterar o domínio."""
from django.utils import timezone


def instante(valor):
    return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M") if valor else "—"


def linha(tipo, registro):
    if tipo == "ativos":
        emprestimos = registro.emprestimos_em_aberto
        situacao = registro.get_situacao_display()
        if emprestimos: situacao += f"\nEmprestado: {emprestimos[0].nome_destino}"
        valores = [f"{registro.dti}\n{registro.patrimonio or 'Sem patrimônio'}", registro.descricao,
                   registro.departamento.nome_exibicao, situacao,
                   f"{registro.especificacoes.get('hostname') or '—'}\n{registro.especificacoes.get('sistema_operacional') or '—'}"]
    elif tipo == "ordens":
        registros = list(registro.registros.all())
        nomes = list(dict.fromkeys([registro.nome_tecnico_abertura] + [r.nome_tecnico for r in registros] + [v.nome_tecnico for r in registros for v in r.revisoes.all()]))
        equipamento = registro.nome_ativo
        if registro.modelo_ativo and registro.modelo_ativo.casefold() not in equipamento.casefold():
            equipamento += f"\n{registro.modelo_ativo}"
        valores = [f"OS {registro.pk}\nDTI {registro.dti_ativo}", equipamento,
                   registro.nome_departamento, f"{registro.get_status_display()}\n{registro.get_resultado_display() or 'Sem resultado'}",
                   instante(registro.aberto_em), "\n".join(nomes)]
    elif tipo == "estoque":
        valores = [registro.nome, f"{registro.get_tipo_display()}\n{registro.capacidade_formatada}".strip(),
                   str(registro.saldo), str(registro.quantidade_minima),
                   "Inativo" if not registro.ativo else ("Estoque baixo" if registro.estoque_baixo else "Regular")]
    elif tipo == "baixas":
        valores = [f"#{registro.pk}\nDTI {registro.dti_ativo}", f"{registro.descricao_ativo}\n{registro.patrimonio_ativo or 'Sem patrimônio'}",
                   registro.nome_departamento, f"{instante(registro.registrado_em)}\n{registro.nome_tecnico}",
                   "\n".join(f"{r['quantidade']} × {r['nome']}" for r in registro.recuperados) or "Nenhuma"]
    elif tipo == "emprestimos":
        valores = [f"#{registro.pk}\nDTI {registro.dti_ativo}", registro.descricao_ativo,
                   f"{registro.nome_origem}\n→ {registro.nome_destino}", registro.recebido_por,
                   f"{registro.get_encerramento_display() or 'Em aberto'}\n{instante(registro.encerrado_em) if registro.encerrado_em else ''}".strip(),
                   f"{instante(registro.registrado_em)}\n{registro.nome_tecnico}"]
    else:
        valores = [f"#{registro.pk}\nDTI {registro.dti_ativo}", f"{registro.descricao_ativo}\n{registro.patrimonio_ativo or 'Sem patrimônio'}",
                   registro.nome_origem, registro.nome_destino, f"{instante(registro.registrado_em)}\n{registro.nome_tecnico}"]
    return {"id": registro.pk, "celulas": valores}
