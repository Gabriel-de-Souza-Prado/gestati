from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from estoque.models import Componente

from .composicao import (
    DO_ESTOQUE, JA_NO_EQUIPAMENTO, ItemComposicao,
    calcular_ram_total_gb, normalizar_itens_composicao,
)


class PreparacaoComposicaoTests(SimpleTestCase):
    def test_agrupa_mesma_especificacao_sem_perder_origem(self):
        itens = normalizar_itens_composicao([
            {"componente_id": 4, "quantidade": 1, "origem": DO_ESTOQUE},
            {"componente_id": 4, "quantidade": 1, "origem": JA_NO_EQUIPAMENTO},
            {"componente_id": 4, "quantidade": 2, "origem": DO_ESTOQUE},
        ])
        self.assertCountEqual(itens, [ItemComposicao(4, 3, DO_ESTOQUE), ItemComposicao(4, 1, JA_NO_EQUIPAMENTO)])

    def test_ordem_do_formulario_nao_muda_resultado_da_confirmacao(self):
        itens = [
            {"componente_id": "3000000000", "quantidade": "2", "origem": DO_ESTOQUE},
            {"componente_id": 1, "quantidade": 1, "origem": JA_NO_EQUIPAMENTO},
        ]
        self.assertEqual(normalizar_itens_composicao(itens), normalizar_itens_composicao(reversed(itens)))

    def test_quantidades_e_origens_invalidas_sao_rejeitadas(self):
        base = {"componente_id": 1, "quantidade": 1, "origem": DO_ESTOQUE}
        for alteracao in ({"quantidade": 0}, {"quantidade": -1}, {"quantidade": 1.5},
                          {"quantidade": True}, {"componente_id": None}, {"origem": "compra"}, {"origem": []}):
            with self.subTest(alteracao=alteracao), self.assertRaises(ValidationError):
                normalizar_itens_composicao([base | alteracao])
        with self.assertRaises(ValidationError):
            normalizar_itens_composicao([base | {"quantidade": 2147483647}, base])

    def test_lista_vazia_nao_inventa_componentes(self):
        self.assertEqual(normalizar_itens_composicao([]), ())
        self.assertEqual(calcular_ram_total_gb([]), Decimal("0"))

    def test_duas_memorias_de_8_gb_resultam_em_16_gb_sem_somar_armazenamento(self):
        ram = Componente(tipo="ram", capacidade=Decimal("8"), unidade_capacidade="GB")
        ssd = Componente(tipo="ssd", capacidade=Decimal("256"), unidade_capacidade="GB")
        self.assertEqual(calcular_ram_total_gb([(ram, 2), (ssd, 1)]), Decimal("16"))

    def test_capacidade_de_ram_inconsistente_nao_vira_total_silenciosamente(self):
        for capacidade, unidade in ((None, "GB"), (Decimal("8"), "TB"), (Decimal("NaN"), "GB")):
            ram = Componente(tipo="ram", capacidade=capacidade, unidade_capacidade=unidade)
            with self.subTest(capacidade=capacidade, unidade=unidade), self.assertRaises(ValidationError):
                calcular_ram_total_gb([(ram, 1)])
