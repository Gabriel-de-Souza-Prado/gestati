"""Regras puras da composição, independentes do formulário e da persistência.

O serviço integrado deverá validar os cadastros e confirmar ativo, composição
e consumo juntos. Estas funções não registram nem consomem estoque.
"""
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
import re

from django.core.exceptions import ValidationError

from core.perfis import PerfilConfiguracao as Perfil


JA_NO_EQUIPAMENTO = "no_equipamento"
DO_ESTOQUE = "estoque"
ORIGENS_COMPOSICAO = (
    (JA_NO_EQUIPAMENTO, "Já veio no equipamento"),
    (DO_ESTOQUE, "Utilizar do estoque da TI"),
)
LIMITE_QUANTIDADE = 2147483647


def validar_composicao_completa(perfil, componentes):
    if perfil not in (Perfil.COMPUTADOR, Perfil.NOTEBOOK):
        return
    tipos = {componente.tipo for componente in componentes}
    grupos = (({"placa_mae"}, "placa-mãe"), ({"processador"}, "processador"), ({"ram"}, "memória RAM"), ({"fonte"}, "fonte/alimentação"), ({"ssd", "hdd"}, "SSD ou HDD"))
    faltantes = [rotulo for valores, rotulo in grupos if not tipos.intersection(valores)]
    if faltantes:
        raise ValidationError("A configuração deve estar completa. Faltam: " + ", ".join(faltantes) + ".")


@dataclass(frozen=True)
class ItemComposicao:
    componente_id: int
    quantidade: int
    origem: str


def _inteiro_positivo(valor, nome, *, limite=LIMITE_QUANTIDADE):
    if not re.fullmatch(r"[0-9]+", str(valor)):
        raise ValidationError(f"{nome} deve ser um número inteiro positivo.")
    numero = int(valor)
    if not 1 <= numero <= limite:
        raise ValidationError(f"{nome} está fora do intervalo permitido.")
    return numero


def normalizar_itens_composicao(itens):
    """Agrupa especificação/origem sem confundir peças compradas com consumo.

    A obrigatoriedade de componentes por categoria pertence à validação do
    cadastro; lista vazia continua representando uma composição vazia.
    """
    grupos = defaultdict(int)
    totais = defaultdict(int)
    origens = {valor for valor, _ in ORIGENS_COMPOSICAO}
    for item in itens:
        if not isinstance(item, Mapping):
            raise ValidationError("Informe os dados do componente, quantidade e origem.")
        componente_id = _inteiro_positivo(item.get("componente_id"), "Componente", limite=9223372036854775807)
        quantidade = _inteiro_positivo(item.get("quantidade"), "Quantidade")
        origem = item.get("origem")
        if not isinstance(origem, str) or origem not in origens:
            raise ValidationError("Informe se a peça já veio no equipamento ou será utilizada do estoque.")
        grupos[componente_id, origem] += quantidade
        totais[componente_id] += quantidade
        if totais[componente_id] > LIMITE_QUANTIDADE:
            raise ValidationError("A quantidade total de um componente excede o intervalo permitido.")
    return tuple(
        ItemComposicao(componente_id, quantidade, origem)
        for (componente_id, origem), quantidade in sorted(grupos.items())
    )


def calcular_ram_total_gb(composicao):
    """Soma capacidade por unidade × quantidade; não mantém total editável.

    Recebe pares (componente, quantidade). Componentes são especificações já
    validadas do catálogo, cuja RAM sempre tem capacidade estruturada em GB.
    """
    total = Decimal("0")
    for componente, quantidade in composicao:
        quantidade = _inteiro_positivo(quantidade, "Quantidade instalada")
        if componente.tipo != "ram":
            continue
        capacidade = componente.capacidade
        if (
            componente.unidade_capacidade != "GB"
            or not isinstance(capacidade, Decimal)
            or not capacidade.is_finite()
            or capacidade <= 0
        ):
            raise ValidationError("A capacidade da memória RAM precisa estar corretamente cadastrada em GB.")
        total += capacidade * quantidade
    return total


def normalizar_itens_servico(itens):
    if not isinstance(itens, (list, tuple)) or len(itens) > 50:
        raise ValidationError("Informe até 50 linhas de peças por serviço.")
    totais = defaultdict(int)
    for item in itens:
        if not isinstance(item, dict) or set(item) != {"componente_id", "quantidade", "acao"}:
            raise ValidationError("Informe componente, quantidade e ação para cada peça.")
        if (type(item["componente_id"]) is not int or not 0 < item["componente_id"] < 2**63
                or type(item["quantidade"]) is not int or not 0 < item["quantidade"] < 2**31
                or item["acao"] not in ("instalar", "retirar_reutilizar", "retirar_sem_retorno")):
            raise ValidationError("Confira o componente, a quantidade inteira positiva e a ação das peças.")
        totais[(item["componente_id"], item["acao"])] += item["quantidade"]
    if any(q >= 2**31 for q in totais.values()):
        raise ValidationError("Quantidade de peças acima do limite permitido.")
    return [{"componente_id": c, "acao": a, "quantidade": q} for (c, a), q in sorted(totais.items())]

