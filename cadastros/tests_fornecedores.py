from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, models, transaction
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse

from .models import Fornecedor
from .services import definir_situacao_fornecedor, excluir_fornecedor, salvar_fornecedor
from .validators import normalizar_cnpj


class CnpjTests(SimpleTestCase):
    def test_aceita_ausencia_e_numerico_com_zeros_iniciais(self):
        self.assertIsNone(normalizar_cnpj(" "))
        self.assertIsNone(normalizar_cnpj(None))
        self.assertEqual(normalizar_cnpj("00.000.000/0001-91"), "00000000000191")
        self.assertEqual(normalizar_cnpj("11222333000181"), "11222333000181")

    def test_exemplo_alfanumerico_da_receita_com_mascara_e_minusculas(self):
        self.assertEqual(normalizar_cnpj("12.abc.345/01de-35"), "12ABC34501DE35")
        self.assertEqual(normalizar_cnpj("12ABC34501DE35"), "12ABC34501DE35")

    def test_rejeita_digitos_errados_formatos_incompletos_e_caracteres_estranhos(self):
        for valor in ("00000000000000", "11.222.333/0001-80", "12ABC34501DE34",
                      "12ABC34501DE3A", "1122233300018", "11 222333000181",
                      "xx11222333000181", "１１222333000181", "12ÁBC34501DE35",
                      "12.ABC345/01DE-35"):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                normalizar_cnpj(valor)


class FornecedorRegrasTests(TestCase):
    def test_campos_opcionais_e_nome_normalizado_para_busca(self):
        fornecedor = salvar_fornecedor(nome="  Comércio   São José  ")
        self.assertEqual(fornecedor.nome, "Comércio São José")
        self.assertEqual(fornecedor.chave_nome, "comercio sao jose")
        self.assertIsNone(fornecedor.cnpj)
        self.assertEqual(fornecedor.telefone, "")
        salvar_fornecedor(nome="Outro fornecedor")
        self.assertEqual(Fornecedor.objects.filter(cnpj__isnull=True).count(), 2)

    def test_nome_igual_nao_bloqueia_empresas_distintas(self):
        salvar_fornecedor(nome="Comércio TI", cnpj="11222333000181")
        salvar_fornecedor(nome="Comércio TI", cnpj="12ABC34501DE35")
        self.assertEqual(Fornecedor.objects.count(), 2)

    def test_rejeita_cnpj_duplicado_inativo_e_edicao_preserva_original(self):
        original = salvar_fornecedor(nome="Original", cnpj="11.222.333/0001-81")
        definir_situacao_fornecedor(fornecedor_id=original.pk, ativo=False)
        outro = salvar_fornecedor(nome="Outro")
        with self.assertRaises(ValidationError):
            salvar_fornecedor(nome="Repetido", cnpj="11222333000181")
        with self.assertRaises(ValidationError):
            salvar_fornecedor(nome="Alterado", cnpj="11222333000181", fornecedor_id=outro.pk)
        outro.refresh_from_db()
        self.assertEqual(outro.nome, "Outro")
        self.assertIsNone(outro.cnpj)
        self.assertEqual(Fornecedor.objects.count(), 2)

    def test_banco_protege_unicidade_e_formato_mesmo_com_update_direto(self):
        salvar_fornecedor(nome="Original", cnpj="12ABC34501DE35")
        outro = salvar_fornecedor(nome="Outro")
        for valor in ("12ABC34501DE35", "", "12abc34501de35", "123"):
            with self.subTest(valor=valor), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Fornecedor.objects.filter(pk=outro.pk).update(cnpj=valor)

    def test_nome_email_e_cnpj_invalidos_nao_salvam(self):
        for dados in ({"nome": "  "}, {"nome": "TI", "email": "invalido"},
                      {"nome": "TI", "cnpj": "12ABC34501DE34"}):
            with self.subTest(dados=dados), self.assertRaises(ValidationError):
                salvar_fornecedor(**dados)
        self.assertFalse(Fornecedor.objects.exists())

    def test_editar_e_limpar_cnpj_preserva_situacao(self):
        fornecedor = salvar_fornecedor(nome="TI", cnpj="11222333000181")
        definir_situacao_fornecedor(fornecedor_id=fornecedor.pk, ativo=False)
        atualizado = salvar_fornecedor(
            nome="São José", fornecedor_id=fornecedor.pk, cnpj="",
            telefone=" +55 64 1234-5678 ramal 12 ", email=" contato@example.com ",
        )
        self.assertFalse(atualizado.ativo)
        self.assertEqual(atualizado.chave_nome, "sao jose")
        self.assertEqual(atualizado.email, "contato@example.com")
        self.assertIsNone(atualizado.cnpj)
        salvar_fornecedor(nome="Novo", cnpj="11222333000181")


class FornecedorFluxoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tecnico = get_user_model().objects.create_user(username="tecnico_fornecedores")

    def setUp(self):
        self.client.force_login(self.tecnico)

    def test_rotas_exigem_login(self):
        fornecedor = salvar_fornecedor(nome="TI")
        self.client.logout()
        for nome in ("listar", "criar", "editar", "situacao", "excluir"):
            kwargs = {"pk": fornecedor.pk} if nome in ("editar", "situacao", "excluir") else {}
            url = reverse(f"cadastros:fornecedor_{nome}", kwargs=kwargs)
            for metodo in (self.client.get, self.client.post):
                with self.subTest(nome=nome, metodo=metodo.__name__):
                    self.assertEqual(metodo(url).status_code, 302)
        self.assertEqual(Fornecedor.objects.count(), 1)

    def test_tecnico_cria_edita_e_recebe_erro_de_duplicacao_por_campo(self):
        url = reverse("cadastros:fornecedor_criar")
        self.assertEqual(self.client.post(url, {"nome": "TI", "cnpj": "12.abc.345/01de-35"}).status_code, 302)
        fornecedor = Fornecedor.objects.get()
        repetido = self.client.post(url, {"nome": "Duplicado", "cnpj": "12ABC34501DE35"})
        self.assertEqual(repetido.status_code, 200)
        self.assertIn("cnpj", repetido.context["form"].errors)
        editar = reverse("cadastros:fornecedor_editar", args=[fornecedor.pk])
        self.assertEqual(self.client.get(editar).context["form"].initial["cnpj"], "12.ABC.345/01DE-35")
        self.assertEqual(self.client.post(editar, {"nome": "Atualizado", "cnpj": fornecedor.cnpj}).status_code, 302)
        self.assertEqual(Fornecedor.objects.get().nome, "Atualizado")

    def test_busca_normalizada_cnpj_formatado_parcial_e_filtro(self):
        fornecedor = salvar_fornecedor(nome="Comércio São José", cnpj="12ABC34501DE35")
        inativo = salvar_fornecedor(nome="Outro")
        definir_situacao_fornecedor(fornecedor_id=inativo.pk, ativo=False)
        url = reverse("cadastros:fornecedor_listar")
        for termo in ("COMERCIO SAO", "12.abc.345/01de-35", "01DE"):
            with self.subTest(termo=termo):
                response = self.client.get(url, {"q": termo})
                self.assertEqual(list(response.context["page_obj"]), [fornecedor])
        response = self.client.get(url, {"situacao": "inativos"})
        self.assertEqual(list(response.context["page_obj"]), [inativo])
        response = self.client.get(url, {"situacao": "inválida"})
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_nome_semelhante_avisa_mas_nao_bloqueia_e_pagina_preserva_filtros(self):
        salvar_fornecedor(nome="Comércio TI")
        response = self.client.post(reverse("cadastros:fornecedor_criar"), {"nome": "COMERCIO TI"}, follow=True)
        self.assertContains(response, "Há outro fornecedor com esse nome")
        for numero in range(16):
            salvar_fornecedor(nome=f"Comércio {numero:02d}")
        response = self.client.get(reverse("cadastros:fornecedor_listar"), {"q": "comercio", "situacao": "ativos"})
        self.assertEqual(len(response.context["page_obj"]), 15)
        self.assertContains(response, "q=comercio&amp;situacao=ativos&amp;page=2")

    def test_situacao_exige_post_valido_e_csrf_em_todas_escritas(self):
        fornecedor = salvar_fornecedor(nome="TI")
        url = reverse("cadastros:fornecedor_situacao", args=[fornecedor.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {"ativo": "qualquer"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"ativo": "0"}).status_code, 302)
        fornecedor.refresh_from_db()
        self.assertFalse(fornecedor.ativo)
        self.assertEqual(self.client.post(url, {"ativo": "1"}).status_code, 302)
        protegido = Client(enforce_csrf_checks=True)
        protegido.force_login(self.tecnico)
        for nome in ("criar", "editar", "situacao", "excluir"):
            args = [] if nome == "criar" else [fornecedor.pk]
            with self.subTest(nome=nome):
                self.assertEqual(protegido.post(reverse(f"cadastros:fornecedor_{nome}", args=args)).status_code, 403)

    def test_exclusao_exige_post_e_urls_inexistentes_retornam_404(self):
        fornecedor = salvar_fornecedor(nome="Temporário")
        url = reverse("cadastros:fornecedor_excluir", args=[fornecedor.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(Fornecedor.objects.filter(pk=fornecedor.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(Fornecedor.objects.exists())
        for nome in ("editar", "situacao", "excluir"):
            url = reverse(f"cadastros:fornecedor_{nome}", args=[fornecedor.pk])
            response = self.client.post(url, {"ativo": "1"}) if nome == "situacao" else self.client.get(url)
            self.assertEqual(response.status_code, 404)


class FornecedorIntegridadeTests(TransactionTestCase):
    def test_cnpj_concorrente_salva_uma_unica_empresa(self):
        barreira = Barrier(2)

        def cadastrar(nome, cnpj):
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                salvar_fornecedor(nome=nome, cnpj=cnpj)
                return "salvo"
            except ValidationError:
                return "duplicado"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = [executor.submit(cadastrar, "A", "12.ABC.345/01DE-35"),
                          executor.submit(cadastrar, "B", "12ABC34501DE35")]
            self.assertCountEqual([r.result(timeout=20) for r in resultados], ["salvo", "duplicado"])
        self.assertEqual(Fornecedor.objects.count(), 1)

    def test_exclusao_bloqueia_vinculo_real(self):
        class VinculoFornecedorTemporario(models.Model):
            fornecedor = models.ForeignKey(Fornecedor, on_delete=models.PROTECT)

            class Meta:
                app_label = "cadastros"
                managed = False
                db_table = "teste_vinculo_fornecedor"

        with connection.schema_editor() as editor:
            editor.create_model(VinculoFornecedorTemporario)
        try:
            fornecedor = salvar_fornecedor(nome="TI")
            VinculoFornecedorTemporario.objects.create(fornecedor=fornecedor)
            with self.assertRaisesMessage(ValidationError, "registros vinculados"):
                excluir_fornecedor(fornecedor_id=fornecedor.pk)
            definir_situacao_fornecedor(fornecedor_id=fornecedor.pk, ativo=False)
            self.assertTrue(Fornecedor.objects.filter(pk=fornecedor.pk, ativo=False).exists())
            self.assertEqual(VinculoFornecedorTemporario.objects.count(), 1)
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(VinculoFornecedorTemporario)
            apps.all_models["cadastros"].pop("vinculofornecedortemporario", None)
            apps.clear_cache()
