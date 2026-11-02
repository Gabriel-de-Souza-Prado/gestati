import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from cadastros.services import definir_situacao_fornecedor, excluir_fornecedor, salvar_fornecedor

from .models import Componente, MovimentoEstoque
from .selectors import componentes_com_saldo
from .services import definir_situacao_componente, excluir_componente, registrar_entrada, salvar_componente


def nova_ram(nome="RAM DDR4 8 GB", **dados):
    return salvar_componente(nome=nome, tipo="ram", capacidade=8, unidade_capacidade="GB", **dados)


class EstoqueBaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tecnico = get_user_model().objects.create_user(username="tecnico_estoque", first_name="Técnico Exemplo")

    def entrada(self, componente, **dados):
        argumentos = dict(componente_id=componente.pk, quantidade=5, origem="compra", data=timezone.localdate(), usuario=self.tecnico, chave_confirmacao=uuid.uuid4())
        argumentos.update(dados)
        return registrar_entrada(**argumentos)

    def saldo(self, componente):
        return componentes_com_saldo().get(pk=componente.pk).saldo


class ComponenteRegrasTests(EstoqueBaseTests):
    def test_catalogo_sem_entrada_saldo_zero_e_alerta_no_limite(self):
        componente = nova_ram(quantidade_minima=5)
        self.assertEqual(self.saldo(componente), 0)
        self.assertTrue(componentes_com_saldo().get(pk=componente.pk).estoque_baixo)
        self.entrada(componente)
        self.assertTrue(componentes_com_saldo().get(pk=componente.pk).estoque_baixo)
        self.entrada(componente, quantidade=1)
        self.assertEqual(self.saldo(componente), 6)
        self.assertFalse(componentes_com_saldo().get(pk=componente.pk).estoque_baixo)

    def test_rejeita_nome_equivalente_inativo_sem_criar_linha_parcial(self):
        componente = nova_ram(nome="  Memória   DDR4 8 GB  ")
        self.assertEqual(componente.nome, "Memória DDR4 8 GB")
        definir_situacao_componente(componente_id=componente.pk, ativo=False)
        with self.assertRaises(ValidationError) as erro:
            nova_ram(nome="MEMORIA DDR4 8 GB")
        self.assertIn("nome", erro.exception.message_dict)
        self.assertEqual(Componente.objects.count(), 1)

    def test_valida_capacidade_e_tipo_e_minimo_sem_erro_interno(self):
        base = dict(nome="Peça", tipo="ram", capacidade=8, unidade_capacidade="GB")
        for alteracoes in ({"capacidade": None}, {"capacidade": 0}, {"capacidade": "inválida"},
                           {"capacidade": Decimal("NaN")}, {"unidade_capacidade": "TB"},
                           {"tipo": "fonte"}, {"tipo": "inexistente"}, {"nome": " "},
                           {"quantidade_minima": -1}, {"quantidade_minima": 1.5}, {"quantidade_minima": True}):
            with self.subTest(alteracoes=alteracoes), self.assertRaises(ValidationError):
                salvar_componente(**(base | alteracoes))
        self.assertFalse(Componente.objects.exists())
        ssd = salvar_componente(nome="SSD NVMe 1 TB", tipo="ssd", capacidade="1", unidade_capacidade="TB")
        self.assertEqual(ssd.capacidade_formatada, "1 TB")
        salvar_componente(nome="Fonte ATX 500 W", tipo="fonte")
        salvar_componente(nome="Peça livre", tipo="outro")

    def test_banco_protege_capacidade_tipo_minimo_e_nome(self):
        componente = nova_ram()
        for alteracoes in ({"capacidade": None}, {"capacidade": 0}, {"unidade_capacidade": "TB"},
                           {"tipo": "xyz"}, {"quantidade_minima": -1}, {"chave_nome": ""}):
            with self.subTest(alteracoes=alteracoes), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Componente.objects.filter(pk=componente.pk).update(**alteracoes)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Componente.objects.create(nome="RAM DDR4 8 GB", tipo="ram", capacidade=8, unidade_capacidade="GB")

    def test_especificacao_com_movimentos_nao_muda_mas_nome_descricao_minimo_podem(self):
        componente = nova_ram()
        self.entrada(componente)
        with self.assertRaises(ValidationError):
            salvar_componente(nome="RAM 16", tipo="ram", capacidade=16, unidade_capacidade="GB", componente_id=componente.pk)
        componente.refresh_from_db()
        self.assertEqual(componente.capacidade, 8)
        self.assertEqual(componente.nome, "RAM DDR4 8 GB")
        salvar_componente(nome="RAM DDR4 8 GB 2666 MHz", tipo="ram", capacidade=8, unidade_capacidade="GB", descricao="Conector DIMM", quantidade_minima=10, componente_id=componente.pk)
        self.assertEqual(self.saldo(componente), 5)
        self.assertTrue(componentes_com_saldo().get(pk=componente.pk).estoque_baixo)

    def test_especificacao_sem_movimentos_pode_ser_corrigida(self):
        componente = nova_ram()
        atualizado = salvar_componente(nome="RAM DDR4 16 GB", tipo="ram", capacidade=16, unidade_capacidade="GB", componente_id=componente.pk)
        self.assertEqual(atualizado.capacidade, 16)
        self.assertEqual(self.saldo(componente), 0)

    def test_excluir_so_sem_vinculos_e_inativar_preserva_saldo_historico(self):
        vazio = salvar_componente(nome="Erro de cadastro", tipo="outro")
        excluir_componente(componente_id=vazio.pk)
        componente = nova_ram()
        fornecedor = salvar_fornecedor(nome="Fornecedor Exemplo")
        self.entrada(componente, fornecedor_id=fornecedor.pk)
        for operacao in (lambda: excluir_componente(componente_id=componente.pk), lambda: excluir_fornecedor(fornecedor_id=fornecedor.pk)):
            with self.assertRaisesMessage(ValidationError, "registros vinculados"):
                operacao()
        definir_situacao_componente(componente_id=componente.pk, ativo=False)
        self.assertEqual(self.saldo(componente), 5)
        self.assertEqual(componente.movimentos.count(), 1)
        self.assertFalse(componentes_com_saldo().get(pk=componente.pk).estoque_baixo)


class EntradaRegrasTests(EstoqueBaseTests):
    def test_entradas_com_fornecedores_distintos_e_sem_fornecedor_somam_quantidades(self):
        componente = nova_ram()
        for nome in ("Empresa A", "Empresa B"):
            fornecedor = salvar_fornecedor(nome=nome)
            self.entrada(componente, quantidade=10, fornecedor_id=fornecedor.pk)
        self.entrada(componente, quantidade=2)
        self.assertEqual(self.saldo(componente), 22)
        self.assertEqual(MovimentoEstoque.objects.count(), 3)

    def test_reenvio_mesma_confirmacao_nao_duplica_nem_aceita_outros_dados(self):
        componente = nova_ram()
        chave = uuid.uuid4()
        primeiro, criado = self.entrada(componente, chave_confirmacao=chave)
        segundo, criado_novamente = self.entrada(componente, chave_confirmacao=chave)
        self.assertTrue(criado)
        self.assertFalse(criado_novamente)
        self.assertEqual(primeiro.pk, segundo.pk)
        with self.assertRaises(ValidationError):
            self.entrada(componente, quantidade=6, chave_confirmacao=chave)
        outro_tecnico = get_user_model().objects.create_user(username="outro_tecnico")
        with self.assertRaises(ValidationError):
            self.entrada(componente, usuario=outro_tecnico, chave_confirmacao=chave)
        self.assertEqual(self.saldo(componente), 5)
        self.assertEqual(MovimentoEstoque.objects.count(), 1)

    def test_reenvio_apos_inativacao_nao_repete_entrada_e_novo_recebimento_e_bloqueado(self):
        componente = nova_ram()
        chave = uuid.uuid4()
        self.entrada(componente, chave_confirmacao=chave)
        definir_situacao_componente(componente_id=componente.pk, ativo=False)
        self.assertFalse(self.entrada(componente, chave_confirmacao=chave)[1])
        with self.assertRaises(ValidationError):
            self.entrada(componente)
        self.assertEqual(self.saldo(componente), 5)

    def test_fornecedor_inativo_e_inexistente_nao_geram_entrada(self):
        componente = nova_ram()
        fornecedor = salvar_fornecedor(nome="Antigo")
        definir_situacao_fornecedor(fornecedor_id=fornecedor.pk, ativo=False)
        for fornecedor_id in (fornecedor.pk, 99999999):
            with self.assertRaises(ValidationError):
                self.entrada(componente, fornecedor_id=fornecedor_id)
        self.assertEqual(self.saldo(componente), 0)

    def test_quantidade_data_e_origem_invalidas_nao_alteram_saldo(self):
        componente = nova_ram()
        for alteracoes in ({"quantidade": 0}, {"quantidade": -1}, {"quantidade": 1.5}, {"quantidade": True},
                           {"quantidade": 2147483648}, {"data": "inválida"},
                           {"data": timezone.localdate() + timedelta(days=1)}, {"origem": "reaproveitamento"},
                           {"chave_confirmacao": "inválida"}, {"usuario": AnonymousUser()}):
            with self.subTest(alteracoes=alteracoes), self.assertRaises(ValidationError):
                self.entrada(componente, **alteracoes)
        self.assertEqual(self.saldo(componente), 0)
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_estoque_existente_e_outro_recebimento_aceitam_origem_justificada(self):
        componente = nova_ram()
        self.entrada(componente, quantidade=3, origem="saldo_inicial", observacao="Contagem das peças já guardadas na TI.")
        self.entrada(componente, quantidade=1, origem="outra_entrada", observacao="Doação recebida pelo setor.")
        self.assertEqual(self.saldo(componente), 4)

    def test_todas_entradas_aceitam_observacao_vazia_sem_repetir_saldo(self):
        componente = nova_ram()
        for origem in ("compra", "saldo_inicial", "outra_entrada"):
            with self.subTest(origem=origem):
                chave = uuid.uuid4()
                movimento, criado = self.entrada(componente, quantidade=2, origem=origem, chave_confirmacao=chave)
                self.assertTrue(criado)
                self.assertEqual(movimento.observacao, "")
                _, repetido = self.entrada(componente, quantidade=2, origem=origem, chave_confirmacao=chave)
                self.assertFalse(repetido)
        self.assertEqual(self.saldo(componente), 6)

    def test_nomes_da_epoca_preservados_e_movimento_sem_edicao_ou_exclusao(self):
        componente = nova_ram()
        fornecedor = salvar_fornecedor(nome="Empresa Original")
        movimento, _ = self.entrada(componente, fornecedor_id=fornecedor.pk)
        salvar_fornecedor(nome="Empresa Renomeada", fornecedor_id=fornecedor.pk)
        salvar_componente(nome="RAM 8 GB DIMM", tipo="ram", capacidade=8, unidade_capacidade="GB", componente_id=componente.pk)
        self.tecnico.first_name = "Outro nome"
        self.tecnico.save()
        movimento.refresh_from_db()
        self.assertEqual(movimento.nome_componente, "RAM DDR4 8 GB")
        self.assertEqual(movimento.nome_fornecedor, "Empresa Original")
        self.assertEqual(movimento.nome_tecnico, "Técnico Exemplo")
        movimento.quantidade = 99
        with self.assertRaises(ValidationError):
            movimento.save()
        with self.assertRaises(ValidationError):
            movimento.delete()
        self.assertEqual(self.saldo(componente), 5)

    def test_banco_rejeita_quantidade_zero_negativa_e_confirmacao_duplicada(self):
        componente = nova_ram()
        movimento, _ = self.entrada(componente)
        for alteracao in ({"quantidade": 0}, {"quantidade": -1}, {"tipo": "invalido"}, {"origem": "invalida"}):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    MovimentoEstoque.objects.filter(pk=movimento.pk).update(**alteracao)
        segundo, _ = self.entrada(componente)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MovimentoEstoque.objects.filter(pk=segundo.pk).update(chave_confirmacao=movimento.chave_confirmacao)


class EstoqueFluxoTests(EstoqueBaseTests):
    def setUp(self):
        self.client.force_login(self.tecnico)

    def test_login_em_todas_rotas_e_csrf_em_todas_escritas(self):
        componente = nova_ram()
        self.client.logout()
        for nome in ("componente_listar", "componente_criar", "componente_detalhar", "componente_editar", "componente_situacao", "componente_excluir", "entrada_criar"):
            args = [componente.pk] if nome in ("componente_detalhar", "componente_editar", "componente_situacao", "componente_excluir") else []
            url = reverse(f"estoque:{nome}", args=args)
            self.assertEqual(self.client.get(url).status_code, 302)
            self.assertEqual(self.client.post(url).status_code, 302)
        protegido = Client(enforce_csrf_checks=True)
        protegido.force_login(self.tecnico)
        for nome in ("componente_criar", "componente_editar", "componente_situacao", "componente_excluir", "entrada_criar"):
            args = [componente.pk] if nome in ("componente_editar", "componente_situacao", "componente_excluir") else []
            self.assertEqual(protegido.post(reverse(f"estoque:{nome}", args=args)).status_code, 403)
        self.assertEqual(MovimentoEstoque.objects.count(), 0)

    def test_tecnico_cadastra_edita_e_duplicacao_aparece_por_campo(self):
        url = reverse("estoque:componente_criar")
        dados = {"nome": "RAM DDR4 8 GB", "tipo": "ram", "capacidade": "8,00", "unidade_capacidade": "GB", "quantidade_minima": "2"}
        self.assertEqual(self.client.post(url, dados).status_code, 302)
        componente = Componente.objects.get()
        self.assertEqual(self.saldo(componente), 0)
        self.assertTrue(componente.acompanhar_estoque)
        self.assertIn("nome", self.client.post(url, dados).context["form"].errors)
        self.assertEqual(self.client.get(reverse("estoque:componente_editar", args=[componente.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("estoque:componente_editar", args=[componente.pk]), dados | {"descricao": "Especificação detalhada"}).status_code, 302)

    def test_entrada_por_formulario_repetido_e_usuario_vem_da_sessao(self):
        componente = nova_ram()
        url = reverse("estoque:entrada_criar")
        get_response = self.client.get(url, {"componente": componente.pk})
        chave = get_response.context["form"]["chave_confirmacao"].value()
        dados = {"componente": componente.pk, "quantidade": 50, "origem": "compra", "data": timezone.localdate().isoformat(), "chave_confirmacao": str(chave), "registrado_por": "999999"}
        self.assertEqual(self.client.post(url, dados).status_code, 302)
        response = self.client.post(url, dados, follow=True)
        self.assertContains(response, "não foi acrescido novamente")
        self.assertEqual(self.saldo(componente), 50)
        self.assertEqual(MovimentoEstoque.objects.get().registrado_por_id, self.tecnico.pk)

    def test_entrada_invalida_mostra_erros_sem_inserir(self):
        componente = nova_ram()
        url = reverse("estoque:entrada_criar")
        dados = {"componente": componente.pk, "quantidade": 0, "origem": "saldo_inicial", "data": timezone.localdate().isoformat(), "chave_confirmacao": str(uuid.uuid4())}
        response = self.client.post(url, dados)
        self.assertIn("quantidade", response.context["form"].errors)
        dados["quantidade"] = 1
        dados["chave_confirmacao"] = "invalida"
        self.assertIn("chave_confirmacao", self.client.post(url, dados).context["form"].errors)
        definir_situacao_componente(componente_id=componente.pk, ativo=False)
        dados["chave_confirmacao"] = str(uuid.uuid4())
        self.assertIn("componente", self.client.post(url, dados).context["form"].errors)
        self.assertEqual(self.saldo(componente), 0)

    def test_filtros_saldo_e_paginacao_nao_repetem_somas_por_join(self):
        componente = nova_ram(nome="Memória DDR4", quantidade_minima=4)
        self.entrada(componente, quantidade=2)
        self.entrada(componente, quantidade=2)
        salvar_componente(nome="Fonte 500 W", tipo="fonte")
        url = reverse("estoque:componente_listar")
        response = self.client.get(url, {"q": "MEMORIA", "tipo": "ram", "estoque": "baixo"})
        self.assertEqual([(c.pk, c.saldo) for c in response.context["page_obj"]], [(componente.pk, 4)])
        self.assertEqual(len(self.client.get(url, {"estoque": "disponivel"}).context["page_obj"]), 1)
        self.assertEqual(len(self.client.get(url, {"tipo": "invalido"}).context["page_obj"]), 0)
        for numero in range(16):
            salvar_componente(nome=f"Fonte {numero:02d}", tipo="fonte")
        response = self.client.get(url, {"tipo": "fonte", "situacao": "ativos"})
        self.assertEqual(len(response.context["page_obj"]), 15)
        self.assertContains(response, "tipo=fonte&amp;situacao=ativos&amp;page=2")
        segunda = self.client.get(url, {"tipo": "fonte", "situacao": "ativos", "page": 2})
        primeira_ids = {c.pk for c in response.context["page_obj"]}
        segunda_ids = {c.pk for c in segunda.context["page_obj"]}
        self.assertFalse(primeira_ids & segunda_ids)
        self.assertEqual(len(primeira_ids | segunda_ids), 17)

    def test_historico_filtrado_nao_altera_saldo_total(self):
        componente = nova_ram()
        self.entrada(componente, quantidade=3, data=timezone.localdate() - timedelta(days=10))
        self.entrada(componente, quantidade=2)
        url = reverse("estoque:componente_detalhar", args=[componente.pk])
        response = self.client.get(url, {"inicio": timezone.localdate().isoformat()})
        self.assertEqual(response.context["componente"].saldo, 5)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertContains(response, "1 movimentação encontrada")
        response = self.client.get(url, {"inicio": timezone.localdate().isoformat(), "fim": "2020-01-01"})
        self.assertTrue(response.context["filtro"].non_field_errors())
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_situacao_exclusao_e_rotas_inexistentes(self):
        componente = nova_ram()
        url = reverse("estoque:componente_situacao", args=[componente.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {"ativo": "invalido"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"ativo": "0"}).status_code, 302)
        self.assertEqual(self.client.post(url, {"ativo": "1"}).status_code, 302)
        excluir = reverse("estoque:componente_excluir", args=[componente.pk])
        self.assertEqual(self.client.get(excluir).status_code, 200)
        self.assertTrue(Componente.objects.filter(pk=componente.pk).exists())
        self.assertEqual(self.client.post(excluir).status_code, 302)
        for nome in ("componente_detalhar", "componente_editar", "componente_excluir"):
            self.assertEqual(self.client.get(reverse(f"estoque:{nome}", args=[componente.pk])).status_code, 404)


class EstoqueConcorrenciaTests(TransactionTestCase):
    def executar_entradas(self, pares):
        usuario = get_user_model().objects.create_user(username="concorrencia_estoque")
        barreira = Barrier(2)

        def registrar(componente_id, chave):
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                return registrar_entrada(componente_id=componente_id, quantidade=5, origem="compra", data=timezone.localdate(), usuario=usuario, chave_confirmacao=chave)[1]
            except ValidationError:
                return "conflito"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = [executor.submit(registrar, *par) for par in pares]
            return [r.result(timeout=20) for r in resultados]

    def test_entradas_distintas_somam_sem_perder_quantidade(self):
        componente = nova_ram()
        self.assertEqual(self.executar_entradas([(componente.pk, uuid.uuid4()), (componente.pk, uuid.uuid4())]), [True, True])
        self.assertEqual(componentes_com_saldo().get(pk=componente.pk).saldo, 10)

    def test_mesma_confirmacao_concorrente_soma_uma_vez(self):
        componente = nova_ram()
        chave = uuid.uuid4()
        self.assertCountEqual(self.executar_entradas([(componente.pk, chave), (componente.pk, chave)]), [True, False])
        self.assertEqual(componentes_com_saldo().get(pk=componente.pk).saldo, 5)
        self.assertEqual(MovimentoEstoque.objects.count(), 1)

    def test_mesma_confirmacao_em_componentes_distintos_nao_soma_ambos(self):
        primeiro, segundo = nova_ram(), nova_ram(nome="RAM DDR3 8 GB")
        chave = uuid.uuid4()
        self.assertCountEqual(self.executar_entradas([(primeiro.pk, chave), (segundo.pk, chave)]), [True, "conflito"])
        self.assertEqual(sum(componentes_com_saldo().values_list("saldo", flat=True)), 5)
        self.assertEqual(MovimentoEstoque.objects.count(), 1)
