from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, models, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from .models import Departamento, IdentificadorDepartamento
from .services import (
    definir_situacao_departamento,
    excluir_departamento,
    salvar_departamento,
)


class DepartamentoRegrasTests(TestCase):
    def test_rejeita_nome_repetido_com_acentos_caixa_e_espacos_diferentes(self):
        salvar_departamento(nome="Secretaria de Saúde", sigla="SMS")
        with self.assertRaises(ValidationError):
            salvar_departamento(nome="  SECRETARIA   DE SAUDE  ")
        self.assertEqual(Departamento.objects.count(), 1)

    def test_sigla_impede_cadastrar_rh_como_outro_departamento(self):
        original = salvar_departamento(nome="Recursos Humanos", sigla="rh")
        with self.assertRaises(ValidationError):
            salvar_departamento(nome="RH")
        self.assertEqual(list(Departamento.objects.values_list("pk", flat=True)), [original.pk])

    def test_nome_existente_impede_usar_sua_identificacao_como_sigla(self):
        salvar_departamento(nome="RH")
        with self.assertRaises(ValidationError):
            salvar_departamento(nome="Recursos Humanos", sigla="RH")
        self.assertEqual(Departamento.objects.count(), 1)

    def test_nome_repetido_tambem_e_protegido_pelo_banco(self):
        salvar_departamento(nome="Saúde")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Departamento.objects.create(nome="SAUDE")

    def test_edicao_sem_mudar_identificacao_funciona(self):
        departamento = salvar_departamento(nome="Recursos Humanos", sigla="RH")
        atualizado = salvar_departamento(
            nome="Recursos Humanos", sigla="RH", departamento_id=departamento.pk
        )
        self.assertEqual(atualizado.pk, departamento.pk)
        self.assertEqual(atualizado.identificadores.count(), 2)

    def test_edicao_renova_identificacao_sem_bloquear_nome_antigo(self):
        departamento = salvar_departamento(nome="Setor incorreto", sigla="XX")
        salvar_departamento(nome="Saúde", sigla="SMS", departamento_id=departamento.pk)
        self.assertEqual(
            set(departamento.identificadores.values_list("chave", flat=True)), {"saude", "sms"}
        )
        salvar_departamento(nome="Setor incorreto", sigla="XX")

    def test_edicao_com_conflito_preserva_cadastro_e_identificadores(self):
        salvar_departamento(nome="Saúde", sigla="SMS")
        departamento = salvar_departamento(nome="Educação", sigla="SME")
        with self.assertRaises(ValidationError):
            salvar_departamento(nome="Saúde", departamento_id=departamento.pk)
        departamento.refresh_from_db()
        self.assertEqual(departamento.nome, "Educação")
        self.assertTrue(departamento.identificadores.filter(chave="sme").exists())

    def test_inativar_preserva_dados_e_impede_nome_duplicado(self):
        departamento = salvar_departamento(nome="Saúde")
        definir_situacao_departamento(departamento_id=departamento.pk, ativo=False)
        departamento.refresh_from_db()
        self.assertFalse(departamento.ativo)
        with self.assertRaises(ValidationError):
            salvar_departamento(nome="SAUDE")
        definir_situacao_departamento(departamento_id=departamento.pk, ativo=True)
        departamento.refresh_from_db()
        self.assertTrue(departamento.ativo)

    def test_excluir_sem_vinculos_remove_somente_o_cadastro_e_seu_indice(self):
        departamento = salvar_departamento(nome="Cadastro duplicado", sigla="CD")
        preservado = salvar_departamento(nome="Educação")
        excluir_departamento(departamento_id=departamento.pk)
        self.assertFalse(Departamento.objects.filter(pk=departamento.pk).exists())
        self.assertFalse(IdentificadorDepartamento.objects.filter(chave="cd").exists())
        self.assertTrue(Departamento.objects.filter(pk=preservado.pk).exists())


class DepartamentoViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tecnico = get_user_model().objects.create_user(username="tecnico")

    def setUp(self):
        self.client.force_login(self.tecnico)

    def test_rotas_de_cadastro_exigem_login(self):
        anonimo = Client()
        departamento = salvar_departamento(nome="Saúde")
        urls = [
            reverse("cadastros:departamento_listar"),
            reverse("cadastros:departamento_criar"),
            reverse("cadastros:departamento_editar", args=[departamento.pk]),
            reverse("cadastros:departamento_excluir", args=[departamento.pk]),
            reverse("cadastros:departamento_situacao", args=[departamento.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(anonimo.get(url).status_code, 302)
                self.assertEqual(anonimo.post(url, {}).status_code, 302)

    def test_tecnico_comum_pode_cadastrar_e_erro_de_duplicata_aparece_no_form(self):
        url = reverse("cadastros:departamento_criar")
        response = self.client.post(url, {"nome": "Recursos Humanos", "sigla": "RH"})
        self.assertRedirects(response, reverse("cadastros:departamento_listar"))
        response = self.client.post(url, {"nome": "RH", "sigla": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "já pertence")
        self.assertEqual(Departamento.objects.count(), 1)

    def test_busca_por_sigla_acentos_e_situacao(self):
        salvar_departamento(nome="Secretaria de Saúde", sigla="SMS")
        educacao = salvar_departamento(nome="Educação", sigla="SME")
        definir_situacao_departamento(departamento_id=educacao.pk, ativo=False)
        url = reverse("cadastros:departamento_listar")
        response = self.client.get(url, {"q": "saude", "situacao": "ativos"})
        self.assertContains(response, "Secretaria de Saúde")
        self.assertNotContains(response, "Educação")
        response = self.client.get(url, {"q": "sme", "situacao": "inativos"})
        self.assertContains(response, "Educação")

    def test_edicao_nao_altera_situacao_silenciosamente(self):
        departamento = salvar_departamento(nome="Saúde")
        definir_situacao_departamento(departamento_id=departamento.pk, ativo=False)
        response = self.client.post(
            reverse("cadastros:departamento_editar", args=[departamento.pk]),
            {"nome": "Secretaria de Saúde", "sigla": "SMS", "ativo": "1"},
        )
        self.assertEqual(response.status_code, 302)
        departamento.refresh_from_db()
        self.assertEqual(departamento.nome, "Secretaria de Saúde")
        self.assertFalse(departamento.ativo)

    def test_situacao_exige_post_valido(self):
        departamento = salvar_departamento(nome="Saúde")
        url = reverse("cadastros:departamento_situacao", args=[departamento.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {"ativo": "qualquer"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"ativo": "0"}).status_code, 302)
        departamento.refresh_from_db()
        self.assertFalse(departamento.ativo)

    def test_exclusao_exige_confirmacao_post(self):
        departamento = salvar_departamento(nome="Temporário")
        url = reverse("cadastros:departamento_excluir", args=[departamento.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(Departamento.objects.filter(pk=departamento.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(Departamento.objects.filter(pk=departamento.pk).exists())

    def test_post_de_alteracao_exige_csrf(self):
        protegido = Client(enforce_csrf_checks=True)
        protegido.force_login(self.tecnico)
        response = protegido.post(
            reverse("cadastros:departamento_criar"), {"nome": "Saúde", "sigla": "SMS"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Departamento.objects.count(), 0)

    def test_paginacao_preserva_busca_e_nao_repete_departamentos(self):
        for numero in range(17):
            salvar_departamento(nome=f"Departamento {numero:02d}", sigla=f"D{numero:02d}")
        response = self.client.get(reverse("cadastros:departamento_listar"), {"q": "Departamento"})
        self.assertEqual(len(response.context["page_obj"]), 15)
        self.assertContains(response, "page=2")
        self.assertContains(response, "q=Departamento")


class DepartamentoIntegridadeTests(TransactionTestCase):
    def test_concorrencia_entre_nome_e_sigla_nao_deixa_cadastro_parcial(self):
        barreira = Barrier(2)

        def cadastrar(nome, sigla):
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                salvar_departamento(nome=nome, sigla=sigla)
                return "salvo"
            except ValidationError:
                return "duplicado"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = [
                executor.submit(cadastrar, "RH", ""),
                executor.submit(cadastrar, "Recursos Humanos", "RH"),
            ]
            self.assertCountEqual([r.result(timeout=20) for r in resultados], ["salvo", "duplicado"])
        self.assertEqual(Departamento.objects.count(), 1)
        self.assertEqual(IdentificadorDepartamento.objects.filter(chave="rh").count(), 1)

    def test_exclusao_bloqueia_vinculo_real_mesmo_se_a_relacao_usasse_cascade(self):
        # Relação criada apenas no banco isolado de testes para verificar a
        # proteção antes da implementação dos módulos de ativos/históricos.
        class VinculoTemporario(models.Model):
            departamento = models.ForeignKey(Departamento, on_delete=models.CASCADE)

            class Meta:
                app_label = "cadastros"
                managed = False
                db_table = "teste_vinculo_departamento"

        with connection.schema_editor() as editor:
            editor.create_model(VinculoTemporario)
        try:
            departamento = salvar_departamento(nome="Saúde")
            VinculoTemporario.objects.create(departamento=departamento)
            with self.assertRaisesMessage(ValidationError, "registros vinculados"):
                excluir_departamento(departamento_id=departamento.pk)
            self.assertTrue(Departamento.objects.filter(pk=departamento.pk).exists())
            self.assertEqual(VinculoTemporario.objects.count(), 1)
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(VinculoTemporario)
            apps.all_models["cadastros"].pop("vinculotemporario", None)
            apps.clear_cache()
