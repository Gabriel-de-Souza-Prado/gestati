from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, models, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from .models import CategoriaAtivo
from .services import (
    adicionar_categorias_iniciais, definir_situacao_categoria,
    excluir_categoria, salvar_categoria,
)


class CategoriaRegrasTests(TestCase):
    def test_normaliza_nome_preservando_apresentacao_e_impede_duplicacao_inativa(self):
        categoria = salvar_categoria(nome="  Estação   de Trabalho  ")
        self.assertEqual(categoria.nome, "Estação de Trabalho")
        self.assertEqual(categoria.chave_nome, "estacao de trabalho")
        definir_situacao_categoria(categoria_id=categoria.pk, ativo=False)
        with self.assertRaises(ValidationError) as erro:
            salvar_categoria(nome="ESTACAO DE TRABALHO")
        self.assertIn("nome", erro.exception.message_dict)
        self.assertEqual(CategoriaAtivo.objects.count(), 1)

    def test_nome_vazio_ou_longo_nao_cria_registro(self):
        for nome in (" \t ", "a" * 161):
            with self.subTest(nome=nome), self.assertRaises(ValidationError):
                salvar_categoria(nome=nome)
        self.assertFalse(CategoriaAtivo.objects.exists())

    def test_banco_impede_duplicacao_e_chave_vazia(self):
        salvar_categoria(nome="Monitor")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CategoriaAtivo.objects.create(nome=" MONITOR ")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CategoriaAtivo.objects.create(nome=" ")

    def test_edicao_com_conflito_preserva_original_e_situacao(self):
        salvar_categoria(nome="Monitor")
        categoria = salvar_categoria(nome="Notebook")
        definir_situacao_categoria(categoria_id=categoria.pk, ativo=False)
        with self.assertRaises(ValidationError):
            salvar_categoria(nome="MONITOR", categoria_id=categoria.pk)
        categoria.refresh_from_db()
        self.assertEqual(categoria.nome, "Notebook")
        self.assertFalse(categoria.ativo)
        atualizado = salvar_categoria(nome="Notebook", categoria_id=categoria.pk)
        self.assertEqual(atualizado.pk, categoria.pk)
        self.assertFalse(atualizado.ativo)
        salvar_categoria(nome="Portátil", categoria_id=categoria.pk)
        salvar_categoria(nome="Notebook")
        self.assertEqual(CategoriaAtivo.objects.count(), 3)

    def test_categorias_iniciais_repetidas_preservam_cadastros_e_inativacao(self):
        categoria = salvar_categoria(nome="  COMPUTADOR ")
        definir_situacao_categoria(categoria_id=categoria.pk, ativo=False)
        salvar_categoria(nome="Impressora")
        self.assertEqual(adicionar_categorias_iniciais(), 4)
        self.assertEqual(adicionar_categorias_iniciais(), 0)
        categoria.refresh_from_db()
        self.assertEqual(categoria.nome, "COMPUTADOR")
        self.assertFalse(categoria.ativo)
        self.assertCountEqual(
            CategoriaAtivo.objects.values_list("nome", flat=True),
            ["COMPUTADOR", "Impressora", "Monitor", "Nobreak", "Notebook", "Switch"],
        )


class CategoriaFluxoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tecnico = get_user_model().objects.create_user(username="tecnico_categorias")

    def setUp(self):
        self.client.force_login(self.tecnico)

    def test_todas_rotas_exigem_login_e_nao_alteram_dados_anonimamente(self):
        categoria = salvar_categoria(nome="Monitor")
        self.client.logout()
        for nome in ("listar", "criar", "iniciais", "editar", "situacao", "excluir"):
            args = [categoria.pk] if nome in ("editar", "situacao", "excluir") else []
            for metodo in (self.client.get, self.client.post):
                with self.subTest(nome=nome, metodo=metodo.__name__):
                    self.assertEqual(metodo(reverse(f"cadastros:categoria_{nome}", args=args)).status_code, 302)
        self.assertEqual(CategoriaAtivo.objects.count(), 1)

    def test_tecnico_cadastra_categoria_adicional_e_erro_aparece_no_campo(self):
        url = reverse("cadastros:categoria_criar")
        self.assertEqual(self.client.post(url, {"nome": "Impressora"}).status_code, 302)
        response = self.client.post(url, {"nome": "IMPRESSORA"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("nome", response.context["form"].errors)
        self.assertEqual(CategoriaAtivo.objects.count(), 1)
        categoria = CategoriaAtivo.objects.get()
        definir_situacao_categoria(categoria_id=categoria.pk, ativo=False)
        url = reverse("cadastros:categoria_editar", args=[categoria.pk])
        self.assertEqual(self.client.get(url).context["form"].initial["nome"], "Impressora")
        self.assertEqual(self.client.post(url, {"nome": "Impressora laser", "ativo": "1"}).status_code, 302)
        categoria.refresh_from_db()
        self.assertEqual(categoria.nome, "Impressora laser")
        self.assertFalse(categoria.ativo)

    def test_busca_normalizada_filtro_e_atalho_nao_confunde_lista_filtrada_vazia(self):
        categoria = salvar_categoria(nome="Estação de Trabalho")
        inativa = salvar_categoria(nome="Monitor")
        definir_situacao_categoria(categoria_id=inativa.pk, ativo=False)
        url = reverse("cadastros:categoria_listar")
        response = self.client.get(url, {"q": "ESTACAO"})
        self.assertEqual(list(response.context["page_obj"]), [categoria])
        response = self.client.get(url, {"situacao": "inativas"})
        self.assertEqual(list(response.context["page_obj"]), [inativa])
        for filtros in ({"q": "não existe"}, {"situacao": "invalida"}):
            response = self.client.get(url, filtros)
            self.assertEqual(response.context["page_obj"].paginator.count, 0)
            self.assertTrue(response.context["tem_categorias"])
            self.assertNotContains(response, "Adicionar categorias iniciais")

    def test_atalho_inicial_exige_post_e_pode_ser_repetido_sem_duplicar(self):
        url = reverse("cadastros:categoria_iniciais")
        response = self.client.get(reverse("cadastros:categoria_listar"))
        self.assertContains(response, "Adicionar categorias iniciais")
        self.assertFalse(CategoriaAtivo.objects.exists())
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(CategoriaAtivo.objects.count(), 5)

    def test_situacao_exige_post_e_valor_valido_ativando_e_inativando(self):
        categoria = salvar_categoria(nome="Monitor")
        url = reverse("cadastros:categoria_situacao", args=[categoria.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {"ativo": "qualquer"}).status_code, 400)
        for valor, esperado in (("0", False), ("1", True)):
            self.assertEqual(self.client.post(url, {"ativo": valor}).status_code, 302)
            categoria.refresh_from_db()
            self.assertEqual(categoria.ativo, esperado)

    def test_exclusao_so_em_post_e_urls_inexistentes_retornam_404(self):
        categoria = salvar_categoria(nome="Temporária")
        url = reverse("cadastros:categoria_excluir", args=[categoria.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(CategoriaAtivo.objects.filter(pk=categoria.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 302)
        for nome in ("editar", "excluir", "situacao"):
            url = reverse(f"cadastros:categoria_{nome}", args=[categoria.pk])
            response = self.client.post(url, {"ativo": "1"}) if nome == "situacao" else self.client.get(url)
            self.assertEqual(response.status_code, 404)

    def test_todas_escritas_exigem_csrf(self):
        categoria = salvar_categoria(nome="Monitor")
        protegido = Client(enforce_csrf_checks=True)
        protegido.force_login(self.tecnico)
        for nome in ("criar", "iniciais", "editar", "situacao", "excluir"):
            args = [categoria.pk] if nome in ("editar", "situacao", "excluir") else []
            self.assertEqual(protegido.post(reverse(f"cadastros:categoria_{nome}", args=args)).status_code, 403)
        self.assertEqual(CategoriaAtivo.objects.count(), 1)

    def test_paginacao_preserva_filtros(self):
        for numero in range(17):
            salvar_categoria(nome=f"Equipamento {numero:02d}")
        response = self.client.get(reverse("cadastros:categoria_listar"), {"q": "Equipamento", "situacao": "ativas"})
        self.assertEqual(len(response.context["page_obj"]), 15)
        self.assertContains(response, "q=Equipamento&amp;situacao=ativas&amp;page=2")


class CategoriaIntegridadeTests(TransactionTestCase):
    def test_cadastro_concorrente_nao_repete_nome_normalizado(self):
        barreira = Barrier(2)

        def cadastrar(nome):
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                salvar_categoria(nome=nome)
                return "salva"
            except ValidationError:
                return "duplicada"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = [executor.submit(cadastrar, "Estação"), executor.submit(cadastrar, "ESTACAO")]
            self.assertCountEqual([r.result(timeout=20) for r in resultados], ["salva", "duplicada"])
        self.assertEqual(CategoriaAtivo.objects.count(), 1)

    def test_atalhos_iniciais_concorrentes_nao_repetem_categorias(self):
        barreira = Barrier(2)

        def adicionar():
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                return adicionar_categorias_iniciais()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = [executor.submit(adicionar), executor.submit(adicionar)]
            self.assertEqual(sum(r.result(timeout=20) for r in resultados), 5)
        self.assertEqual(CategoriaAtivo.objects.count(), 5)

    def test_exclusao_com_vinculo_real_preserva_categoria_e_relacionado(self):
        class VinculoCategoriaTemporario(models.Model):
            categoria = models.ForeignKey(CategoriaAtivo, on_delete=models.PROTECT)

            class Meta:
                app_label = "cadastros"
                managed = False
                db_table = "teste_vinculo_categoria"

        with connection.schema_editor() as editor:
            editor.create_model(VinculoCategoriaTemporario)
        try:
            categoria = salvar_categoria(nome="Monitor")
            VinculoCategoriaTemporario.objects.create(categoria=categoria)
            with self.assertRaisesMessage(ValidationError, "registros vinculados"):
                excluir_categoria(categoria_id=categoria.pk)
            definir_situacao_categoria(categoria_id=categoria.pk, ativo=False)
            self.assertTrue(CategoriaAtivo.objects.filter(pk=categoria.pk, ativo=False).exists())
            self.assertEqual(VinculoCategoriaTemporario.objects.count(), 1)
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(VinculoCategoriaTemporario)
            apps.all_models["cadastros"].pop("vinculocategoriatemporario", None)
            apps.clear_cache()
