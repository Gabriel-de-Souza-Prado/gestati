from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from cadastros.services import excluir_departamento, salvar_categoria, salvar_departamento, salvar_fornecedor
from estoque.models import Componente, MovimentoEstoque
from estoque.selectors import componentes_com_saldo
from estoque.services import registrar_entrada, salvar_componente
from .composicao import DO_ESTOQUE, JA_NO_EQUIPAMENTO, calcular_ram_total_gb
from .forms import AtivoForm
from .models import Ativo, ComponenteInstalado, IntervencaoComponente
from .selectors import ativos_para_consulta, filtrar_busca_ativos
from .services import CAMPOS_ATIVO, cadastrar_ativo, editar_ativo


def preparar_cadastros():
    usuario = get_user_model().objects.create_user(username="ti_ativos")
    categoria = salvar_categoria(nome="Computador", perfil_configuracao="computador")
    departamento = salvar_departamento(nome="Saúde", sigla="SMS")
    componentes = {}
    for tipo, nome in (("placa_mae", "Placa-mãe Exemplo"), ("processador", "Processador Exemplo"), ("ram", "RAM 8 GB"), ("fonte", "Fonte Exemplo"), ("ssd", "SSD 256 GB")):
        capacidade = {"ram": 8, "ssd": 256}.get(tipo)
        componentes[tipo] = salvar_componente(nome=nome, tipo=tipo, capacidade=capacidade, unidade_capacidade="GB" if capacidade else "")
    return usuario, categoria, departamento, componentes


class BaseAtivosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario, cls.categoria, cls.departamento, cls.componentes = preparar_cadastros()

    def dados(self, dti="0010", **alteracoes):
        return {"nome": "Computador de atendimento", "dti": dti, "categoria_id": self.categoria.pk, "departamento_id": self.departamento.pk, **alteracoes}

    def itens(self, origem=JA_NO_EQUIPAMENTO):
        return [{"componente_id": c.pk, "quantidade": 2 if tipo == "ram" else 1, "origem": origem} for tipo, c in self.componentes.items()]

    def cadastrar(self, dados=None, itens=None, chave=None, **opcionais):
        return cadastrar_ativo(dados=dados or self.dados(), itens=self.itens() if itens is None else itens, especificacoes=opcionais.get("especificacoes", {}), extras=opcionais.get("extras", []), usuario=self.usuario, chave_confirmacao=chave or uuid.uuid4())

    def entrada(self, tipo, quantidade):
        return registrar_entrada(componente_id=self.componentes[tipo].pk, quantidade=quantidade, origem="compra", data=timezone.localdate(), usuario=self.usuario, chave_confirmacao=uuid.uuid4())

    def dados_edicao(self, ativo, **alteracoes):
        return {**{campo: getattr(ativo, campo) for campo in CAMPOS_ATIVO}, **alteracoes}


class CadastroAtivoTests(BaseAtivosTests):
    def test_comprado_completo_registra_16_gb_sem_consumir_saldo_zero(self):
        ativo, criado = self.cadastrar()
        linhas = list(ativo.componentes_instalados.select_related("componente"))
        self.assertTrue(criado)
        self.assertEqual(calcular_ram_total_gb([(l.componente, l.quantidade) for l in linhas]), Decimal("16"))
        self.assertEqual(len(linhas), 5)
        self.assertFalse(MovimentoEstoque.objects.exists())
        self.assertEqual(IntervencaoComponente.objects.count(), 5)

    def test_montagem_consume_cada_quantidade_uma_unica_vez(self):
        for tipo in self.componentes:
            self.entrada(tipo, 5)
        chave = uuid.uuid4()
        ativo, _ = self.cadastrar(itens=self.itens(DO_ESTOQUE), chave=chave)
        repetido, criado = self.cadastrar(itens=list(reversed(self.itens(DO_ESTOQUE))), chave=chave)
        self.assertEqual(repetido.pk, ativo.pk)
        self.assertFalse(criado)
        saldos = {c.tipo: c.saldo for c in componentes_com_saldo()}
        self.assertEqual(saldos["ram"], 3)
        self.assertEqual(saldos["ssd"], 4)
        self.assertEqual(MovimentoEstoque.objects.filter(tipo="saida").count(), 5)
        self.assertEqual(Ativo.objects.count(), 1)

    def test_composicao_mista_agrega_ram_mas_consume_so_uma_unidade(self):
        self.entrada("ram", 2)
        itens = self.itens()
        for item in itens:
            if item["componente_id"] == self.componentes["ram"].pk:
                item["quantidade"] = 1
        itens.append({"componente_id": self.componentes["ram"].pk, "quantidade": 1, "origem": DO_ESTOQUE})
        ativo, _ = self.cadastrar(itens=itens)
        self.assertEqual(ativo.componentes_instalados.get(componente=self.componentes["ram"]).quantidade, 2)
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo, 1)
        self.assertEqual(MovimentoEstoque.objects.filter(tipo="saida").count(), 1)

    def test_falha_no_segundo_consumo_reverte_ativo_composicao_eventos_e_primeira_saida(self):
        self.entrada("ram", 2)
        itens = self.itens()
        for item in itens:
            if item["componente_id"] in (self.componentes["ram"].pk, self.componentes["ssd"].pk):
                item["origem"] = DO_ESTOQUE
        with self.assertRaisesMessage(ValidationError, "Estoque insuficiente"):
            self.cadastrar(itens=itens)
        self.assertEqual(Ativo.objects.count(), 0)
        self.assertEqual(ComponenteInstalado.objects.count(), 0)
        self.assertEqual(IntervencaoComponente.objects.count(), 0)
        self.assertEqual(MovimentoEstoque.objects.count(), 1)
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo, 2)

    def test_computador_e_notebook_exigem_todos_grupos_essenciais(self):
        for perfil in ("computador", "notebook"):
            categoria = salvar_categoria(nome=f"Categoria {perfil}", perfil_configuracao=perfil)
            with self.subTest(perfil=perfil), self.assertRaisesMessage(ValidationError, "configuração deve estar completa"):
                self.cadastrar(dados=self.dados(categoria_id=categoria.pk), itens=self.itens()[:-1])
        self.assertFalse(Ativo.objects.exists())

    def test_dti_preserva_zeros_letras_hifens_e_patrimonio_opcional(self):
        primeiro, _ = self.cadastrar(dados=self.dados(dti="0010", numero_serie="REPETIDA"))
        segundo, _ = self.cadastrar(dados=self.dados(dti="10", numero_serie="REPETIDA"))
        terceiro, _ = self.cadastrar(dados=self.dados(dti=" ab-0010 "))
        self.assertNotEqual(primeiro.pk, segundo.pk)
        self.assertEqual(terceiro.dti, "AB-0010")
        self.assertEqual(Ativo.objects.filter(patrimonio__isnull=True).count(), 3)
        with self.assertRaises(ValidationError):
            self.cadastrar(dados=self.dados(dti="ab-0010"))
        with self.assertRaises(ValidationError):
            self.cadastrar(dados=self.dados(dti="10/20"))

    def test_patrimonio_repetido_falha_sem_consumir_pecas(self):
        self.cadastrar(dados=self.dados(patrimonio="0005"))
        with self.assertRaises(ValidationError):
            self.cadastrar(dados=self.dados(dti="20", patrimonio="0005"))
        self.assertEqual(Ativo.objects.count(), 1)
        self.assertEqual(IntervencaoComponente.objects.count(), 5)

    def test_confirmacao_reutilizada_com_outros_dados_e_rejeitada(self):
        chave = uuid.uuid4()
        self.cadastrar(chave=chave)
        with self.assertRaisesMessage(ValidationError, "outros dados"):
            self.cadastrar(dados=self.dados(dti="OUTRO"), chave=chave)
        self.assertEqual(Ativo.objects.count(), 1)

    def test_banco_protege_identificadores_e_formato(self):
        primeiro, _ = self.cadastrar(dados=self.dados(patrimonio="P-001"))
        segundo, _ = self.cadastrar(dados=self.dados(dti="20"))
        for alteracoes in ({"dti": primeiro.dti}, {"patrimonio": primeiro.patrimonio}, {"dti": "ab 1"}, {"patrimonio": ""}):
            with self.subTest(alteracoes=alteracoes), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Ativo.objects.filter(pk=segundo.pk).update(**alteracoes)

    def test_peca_instalada_sem_estoque_nao_pode_ser_reinterpretada(self):
        self.cadastrar()
        self.assertEqual(MovimentoEstoque.objects.count(), 0)
        with self.assertRaisesMessage(ValidationError, "já foi utilizado"):
            salvar_componente(nome="RAM 16 GB", tipo="ram", capacidade=16, unidade_capacidade="GB", componente_id=self.componentes["ram"].pk)
        with self.assertRaisesMessage(ValidationError, "registros vinculados"):
            excluir_departamento(departamento_id=self.departamento.pk)
        with self.assertRaises(ValidationError):
            salvar_categoria(nome="Computador", perfil_configuracao="generico", categoria_id=self.categoria.pk)

    def test_generico_aceita_extras_sem_componentes_e_escapa_html_na_tela(self):
        categoria = salvar_categoria(nome="Projetor", perfil_configuracao="generico")
        ativo, _ = self.cadastrar(dados=self.dados(categoria_id=categoria.pk), itens=[], extras=[{"campo": "Luminosidade", "valor": "3500 lúmens"}, {"campo": "Detalhe", "valor": "<script>alert(1)</script>"}])
        self.client.force_login(self.usuario)
        response = self.client.get(reverse("ativos:ativo_detalhar", args=[ativo.pk]))
        self.assertContains(response, "3500 lúmens")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_especificacoes_e_extras_incoerentes_rejeitados(self):
        for especificacoes, extras in (({"ram_total": 999}, []), ({}, [{"campo": "DTI", "valor": "999"}])):
            with self.assertRaises(ValidationError):
                self.cadastrar(especificacoes=especificacoes, extras=extras)
        categoria = salvar_categoria(nome="Switch", perfil_configuracao="switch")
        with self.assertRaises(ValidationError):
            self.cadastrar(dados=self.dados(categoria_id=categoria.pk), itens=[], especificacoes={"portas": -1})

    def test_dados_de_compra_desconhecidos_nao_inventam_garantia_ou_modelo(self):
        ativo, _ = self.cadastrar()
        self.assertIsNone(ativo.fornecedor_id)
        self.assertIsNone(ativo.valor_aquisicao)
        self.assertIsNone(ativo.data_aquisicao)
        self.assertEqual(ativo.modelo, "")
        self.assertEqual(ativo.numero_serie, "")
        self.assertEqual(ativo.garantia, "nao_informada")
        self.assertFalse(ativo.esta_em_garantia())

    def test_garantia_valida_e_periodo_incompleto_invalido(self):
        hoje = timezone.localdate()
        ativo, _ = self.cadastrar(dados=self.dados(garantia="com_garantia", inicio_garantia=hoje, fim_garantia=hoje + timedelta(days=365)))
        self.assertTrue(ativo.esta_em_garantia())
        self.assertFalse(ativo.esta_em_garantia(hoje + timedelta(days=366)))
        for dados in (self.dados(dti="20", garantia="com_garantia"), self.dados(dti="20", garantia="nao_informada", inicio_garantia=hoje)):
            with self.assertRaises(ValidationError):
                self.cadastrar(dados=dados)

    def test_edicao_metadados_nao_mexe_em_pecas_e_rejeita_versao_antiga(self):
        ativo, _ = self.cadastrar()
        editar_ativo(ativo_id=ativo.pk, dados=self.dados_edicao(ativo, modelo="Modelo Exemplo"), especificacoes={"hostname": "SAUDE-01"}, extras=[], versao=1)
        ativo.refresh_from_db()
        self.assertEqual(ativo.modelo, "Modelo Exemplo")
        self.assertEqual(ativo.versao, 2)
        self.assertEqual(ativo.componentes_instalados.count(), 5)
        self.assertEqual(IntervencaoComponente.objects.count(), 5)
        self.assertFalse(MovimentoEstoque.objects.exists())
        with self.assertRaisesMessage(ValidationError, "outra pessoa"):
            editar_ativo(ativo_id=ativo.pk, dados=self.dados_edicao(ativo, modelo="Antigo"), especificacoes={}, extras=[], versao=1)

    def test_edicao_nao_troca_departamento_sem_transferencia(self):
        ativo, _ = self.cadastrar()
        outro = salvar_departamento(nome="Educação")
        with self.assertRaisesMessage(ValidationError, "transferência"):
            editar_ativo(ativo_id=ativo.pk, dados=self.dados_edicao(ativo, departamento_id=outro.pk), especificacoes={}, extras=[], versao=1)

    def test_busca_nao_confunde_dti_e_patrimonio_e_serie_repetida(self):
        primeiro, _ = self.cadastrar(dados=self.dados(dti="10", patrimonio="30", numero_serie="XYZ"))
        segundo, _ = self.cadastrar(dados=self.dados(dti="20", patrimonio="10", numero_serie="XYZ"))
        consulta = ativos_para_consulta()
        self.assertEqual(list(filtrar_busca_ativos(consulta, "10", "dti")), [primeiro])
        self.assertEqual(list(filtrar_busca_ativos(consulta, "10", "patrimonio")), [segundo])
        self.assertEqual(filtrar_busca_ativos(consulta, "XYZ", "serie").count(), 2)

    def test_nao_existe_saida_avulsa_sem_intervencao(self):
        self.entrada("ram", 5)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MovimentoEstoque.objects.filter(tipo="entrada").update(tipo="saida", origem="aplicacao")


class AtivoHttpTests(BaseAtivosTests):
    def setUp(self):
        self.client.force_login(self.usuario)

    def formulario_post(self):
        response = self.client.get(reverse("ativos:ativo_criar"))
        dados = {"nome": "PC Exemplo", "dti": "0010", "categoria": self.categoria.pk, "departamento": self.departamento.pk, "situacao": "em_uso", "garantia": "nao_informada", "chave_confirmacao": str(response.context["form"]["chave_confirmacao"].value()), "pecas-TOTAL_FORMS": "5", "pecas-INITIAL_FORMS": "0"}
        for indice, item in enumerate(self.itens()):
            dados.update({f"pecas-{indice}-componente": item["componente_id"], f"pecas-{indice}-quantidade": item["quantidade"], f"pecas-{indice}-origem": item["origem"]})
        return dados

    def test_login_csrf_e_metodos(self):
        ativo, _ = self.cadastrar()
        self.client.logout()
        for nome in ("ativo_listar", "ativo_criar", "ativo_detalhar", "ativo_editar", "catalogo_componentes"):
            args = [ativo.pk] if nome in ("ativo_detalhar", "ativo_editar") else []
            self.assertEqual(self.client.get(reverse(f"ativos:{nome}", args=args)).status_code, 302)
        protegido = Client(enforce_csrf_checks=True)
        protegido.force_login(self.usuario)
        self.assertEqual(protegido.post(reverse("ativos:ativo_criar"), {}).status_code, 403)
        self.assertEqual(protegido.post(reverse("ativos:ativo_editar", args=[ativo.pk]), {}).status_code, 403)

    def test_cadastro_via_formulario_e_reenvio_mantem_uma_composicao(self):
        dados = self.formulario_post()
        response = self.client.post(reverse("ativos:ativo_criar"), dados)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Ativo.objects.count(), 1)
        self.assertEqual(self.client.post(reverse("ativos:ativo_criar"), dados).status_code, 302)
        self.assertEqual(IntervencaoComponente.objects.count(), 5)
        ativo = Ativo.objects.get()
        pagina = self.client.get(reverse("ativos:ativo_detalhar", args=[ativo.pk]))
        self.assertEqual(pagina.context["ram_total"], 16)
        self.assertEqual(ativo.componentes_instalados.get(componente=self.componentes["ram"]).quantidade, 2)
        self.assertContains(pagina, self.componentes["ram"].nome)

    def test_cadastro_incompleto_falha_e_chave_e_preservada(self):
        dados = self.formulario_post()
        dados["pecas-0-DELETE"] = "on"
        response = self.client.post(reverse("ativos:ativo_criar"), dados)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "configuração deve estar completa")
        self.assertEqual(str(response.context["form"]["chave_confirmacao"].value()), dados["chave_confirmacao"])
        self.assertFalse(Ativo.objects.exists())

    def test_campos_por_perfil_e_catalogo_ajax(self):
        response = self.client.get(reverse("ativos:ativo_criar"))
        self.assertNotContains(response, 'data-profile="generico"')
        self.assertNotContains(response, 'data-profile="nobreak"')
        self.assertContains(response, 'data-profile="computador"')
        self.assertNotIn("nome", response.context["form"].fields)
        response = self.client.get(reverse("ativos:catalogo_componentes"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["componentes"]), 5)
        self.assertEqual(self.client.post(reverse("ativos:catalogo_componentes")).status_code, 405)

    def test_edicao_exige_versao_e_nao_consumo_por_campos_forjados(self):
        dados = self.formulario_post()
        self.client.post(reverse("ativos:ativo_criar"), dados)
        ativo = Ativo.objects.get()
        dados["versao"] = "1"
        dados["modelo"] = "PC Genérico"
        dados["pecas-0-origem"] = DO_ESTOQUE
        response = self.client.post(reverse("ativos:ativo_editar", args=[ativo.pk]), dados)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MovimentoEstoque.objects.exists())
        self.assertEqual(ativo.intervencoes.count(), 5)

    def test_garantia_usa_datas_explicitas_inclusive_fevereiro_bissexto(self):
        dados = self.formulario_post() | {"garantia": "com_garantia", "inicio_garantia": "2024-01-31", "fim_garantia": "2024-02-29"}
        response = self.client.post(reverse("ativos:ativo_criar"), dados)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Ativo.objects.get().fim_garantia, date(2024, 2, 29))


class AtivoConcorrenciaTests(TransactionTestCase):
    def preparar(self):
        self.usuario, self.categoria, self.departamento, self.componentes = preparar_cadastros()
        registrar_entrada(componente_id=self.componentes["ram"].pk, quantidade=1, origem="compra", data=timezone.localdate(), usuario=self.usuario, chave_confirmacao=uuid.uuid4())

    def executar(self, mesmos_dados):
        self.preparar()
        barreira = Barrier(2)
        chave = uuid.uuid4()
        itens = [{"componente_id": c.pk, "quantidade": 1, "origem": DO_ESTOQUE if tipo == "ram" else JA_NO_EQUIPAMENTO} for tipo, c in self.componentes.items()]

        def cadastrar(indice):
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                ativo, criado = cadastrar_ativo(dados={"nome": "PC", "dti": "0010" if mesmos_dados else str(indice), "categoria_id": self.categoria.pk, "departamento_id": self.departamento.pk}, itens=itens, especificacoes={}, extras=[], usuario=self.usuario, chave_confirmacao=chave if mesmos_dados else uuid.uuid4())
                return "criado" if criado else "repetido"
            except ValidationError:
                return "rejeitado"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = [executor.submit(cadastrar, i) for i in (1, 2)]
            return [r.result(timeout=25) for r in resultados]

    def test_duas_montagens_disputando_uma_ram_so_uma_e_confirmada(self):
        self.assertCountEqual(self.executar(False), ["criado", "rejeitado"])
        self.assertEqual(Ativo.objects.count(), 1)
        self.assertEqual(ComponenteInstalado.objects.count(), 5)
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo, 0)
        self.assertEqual(MovimentoEstoque.objects.filter(tipo="saida").count(), 1)

    def test_reenvio_concorrente_mesma_chave_consumo_uma_vez(self):
        self.assertCountEqual(self.executar(True), ["criado", "repetido"])
        self.assertEqual(Ativo.objects.count(), 1)
        self.assertEqual(MovimentoEstoque.objects.filter(tipo="saida").count(), 1)
