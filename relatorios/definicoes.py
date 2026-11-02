"""Metadados de apresentação compartilhados por consulta e documento."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Definicao:
    titulo: str
    descricao: str
    colunas: tuple
    larguras: tuple
    detalhe: str


RELATORIOS = {
    "ativos": Definicao("Ativos", "Equipamentos cadastrados, vínculo atual e situação de uso.",
        ("DTI / patrimônio", "Equipamento", "Departamento de vínculo", "Situação", "Nome na rede / SO"),
        (16, 24, 21, 19, 20), "ativos:ativo_detalhar"),
    "ordens": Definicao("Ordens de serviço", "Atendimentos filtrados pela data de abertura e pelos técnicos que participaram.",
        ("OS / DTI", "Equipamento", "Departamento na abertura", "Etapa / resultado", "Aberta em", "Técnicos participantes"),
        (12, 21, 19, 17, 12, 19), "ordens:detalhar"),
    "estoque": Definicao("Estoque de componentes", "Saldo atual das especificações controladas no estoque.",
        ("Componente", "Tipo / capacidade", "Disponível", "Mínimo", "Situação / alerta"),
        (36, 24, 12, 12, 16), "estoque:componente_detalhar"),
    "transferencias": Definicao("Transferências", "Mudanças definitivas de vínculo, filtradas pela data do registro.",
        ("Registro / DTI", "Equipamento / patrimônio", "Origem", "Destino", "Data / técnico"),
        (14, 26, 20, 20, 20), "movimentacoes:detalhar"),
    "emprestimos": Definicao("Empréstimos", "Destinos temporários, recebedores e encerramentos; período baseado no registro do empréstimo.",
        ("Registro / DTI", "Equipamento", "Origem → destino", "Quem recebeu", "Situação / encerramento", "Data / técnico"),
        (13, 19, 23, 16, 15, 14), "movimentacoes:detalhar"),
    "baixas": Definicao("Baixas de equipamentos", "Equipamentos retirados de uso e quantidades recuperadas; período baseado no registro da baixa.",
        ("Registro / DTI", "Equipamento / patrimônio", "Departamento na baixa", "Data / técnico", "Peças recuperadas"),
        (14, 25, 21, 18, 22), "baixas:detalhar"),
}
