from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import SESSION_KEY
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from .forms import DadosUsuarioForm
from .models import Usuario
from .services import redefinir_senha, salvar_usuario, trocar_senha

TEMP = "Provisorio!29-acesso"
PESSOAL = "Pessoal!47-caderno"


class ContasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_superuser("gestor", password="Gestor!48-local")
        cls.ti = Usuario.objects.create_user("tecnico", first_name="Técnico", password="Tecnico!73-local")

    def dados(self, **extras):
        return {"username": "novotecnico", "nome": "Pessoa", "sobrenome": "Exemplo", "email": "",
            "perfil": "ti", "ativo": True, **extras}

    def novo(self, **extras):
        return salvar_usuario(autor=self.admin, dados=self.dados(**extras), senha_temporaria=TEMP)

    def test_criacao_tem_hash_troca_obrigatoria_e_nao_concede_privilegios_tecnicos(self):
        usuario = self.novo(perfil="administrador")
        self.assertTrue(usuario.check_password(TEMP))
        self.assertNotEqual(usuario.password, TEMP)
        self.assertTrue(usuario.deve_trocar_senha)
        self.assertTrue(usuario.administrador_ti)
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertEqual(usuario.user_permissions.count(), 0)

    def test_usuario_comum_e_admin_pendente_nao_podem_administrar_pelo_servico(self):
        for ator in (self.ti, self.novo(perfil="administrador")):
            with self.subTest(ator=ator.pk), self.assertRaises(PermissionDenied):
                salvar_usuario(autor=ator, dados=self.dados(username="invasao"), senha_temporaria=TEMP)
        self.assertFalse(Usuario.objects.filter(username="invasao").exists())

    def test_ator_desatualizado_inativo_ou_rebaixado_e_revalidado(self):
        gestor = Usuario.objects.create_user("administrador", administrador_ti=True)
        Usuario.objects.filter(pk=gestor.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            salvar_usuario(autor=gestor, dados=self.dados(), senha_temporaria=TEMP)
        Usuario.objects.filter(pk=gestor.pk).update(is_active=True, administrador_ti=False)
        with self.assertRaises(PermissionDenied):
            salvar_usuario(autor=gestor, dados=self.dados(), senha_temporaria=TEMP)

    def test_nome_usuario_email_perfil_e_senha_invalidos_nao_criam_conta(self):
        for dados, senha in ((self.dados(nome=""), TEMP), (self.dados(username="com espaço"), TEMP),
                (self.dados(email="ruim"), TEMP), (self.dados(perfil="superuser"), TEMP),
                (self.dados(ativo="sim"), TEMP), (self.dados(), "123")):
            with self.subTest(dados=dados), self.assertRaises(ValidationError):
                salvar_usuario(autor=self.admin, dados=dados, senha_temporaria=senha)
        self.assertEqual(Usuario.objects.count(), 2)

    def test_nome_de_usuario_duplicado_mesmo_inativo_ou_com_caixa_diferente(self):
        self.novo(username="ContaExistente", ativo=False)
        with self.assertRaises(ValidationError):
            self.novo(username="contaexistente")

    def test_edicao_preserva_senha_e_privilegios_previos_e_rejeita_versao_antiga(self):
        senha = self.ti.password
        salvar_usuario(autor=self.admin, usuario_id=self.ti.pk, versao=1,
            dados=self.dados(username="tecnico", perfil="administrador"))
        self.ti.refresh_from_db()
        self.assertEqual(self.ti.password, senha)
        self.assertTrue(self.ti.administrador_ti)
        self.assertFalse(self.ti.is_superuser)
        with self.assertRaises(ValidationError):
            salvar_usuario(autor=self.admin, usuario_id=self.ti.pk, versao=1, dados=self.dados())

    def test_propria_inativacao_rebaixamento_e_perfil_tecnico_sao_protegidos(self):
        for extras in ({"ativo": False, "perfil": "administrador"}, {"perfil": "ti"}):
            with self.subTest(extras=extras), self.assertRaises(ValidationError):
                salvar_usuario(autor=self.admin, usuario_id=self.admin.pk, versao=1,
                    dados=self.dados(username="gestor", **extras))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active and self.admin.is_superuser)

    def test_inativacao_preserva_autoria_e_revoga_acesso_da_sessao(self):
        from ativos.tests_integracao import preparar_cadastros
        autor, *_ = preparar_cadastros()
        self.client.force_login(autor)
        salvar_usuario(autor=self.admin, usuario_id=autor.pk, versao=1,
            dados=self.dados(username=autor.username, ativo=False))
        self.assertTrue(Usuario.objects.filter(pk=autor.pk).exists())
        self.assertRedirects(self.client.get(reverse("inicio")), "/entrar/?next=/", fetch_redirect_response=False)
        self.assertFalse(self.client.login(username=autor.username, password=TEMP))

    def test_admin_inativo_preserva_perfil_ao_reabrir_formulario(self):
        pessoa = self.novo(perfil="administrador", ativo=False)
        self.assertEqual(DadosUsuarioForm(usuario=pessoa).initial["perfil"], "administrador")

    def test_troca_inicial_valida_libera_acesso_e_nao_aceita_senha_atual(self):
        pessoa = self.novo()
        for atual, nova in (("incorreta", PESSOAL), (TEMP, "123"), (TEMP, TEMP)):
            with self.subTest(atual_correta=atual == TEMP), self.assertRaises(ValidationError):
                trocar_senha(usuario_id=pessoa.pk, senha_atual=atual, nova_senha=nova)
        pessoa.refresh_from_db()
        self.assertTrue(pessoa.deve_trocar_senha and pessoa.check_password(TEMP))
        trocar_senha(usuario_id=pessoa.pk, senha_atual=TEMP, nova_senha=PESSOAL)
        pessoa.refresh_from_db()
        self.assertFalse(pessoa.deve_trocar_senha)
        self.assertTrue(pessoa.check_password(PESSOAL))

    def test_redefinicao_exige_nova_troca_e_invalida_sessoes_anteriores(self):
        self.client.force_login(self.ti)
        redefinir_senha(autor=self.admin, usuario_id=self.ti.pk, versao=1, senha_temporaria=TEMP)
        self.ti.refresh_from_db()
        self.assertTrue(self.ti.deve_trocar_senha and self.ti.check_password(TEMP))
        self.assertRedirects(self.client.get(reverse("inicio")), "/entrar/?next=/", fetch_redirect_response=False)
        with self.assertRaises(ValidationError):
            redefinir_senha(autor=self.admin, usuario_id=self.admin.pk, versao=1, senha_temporaria=TEMP)

    def test_primeiro_acesso_bloqueia_rotas_diretas_pdf_admin_e_post_sem_efeitos(self):
        pessoa = self.novo()
        self.client.force_login(pessoa)
        for rota in ("/", "/usuarios/", "/admin/", "/ordens/1/pdf/", "/relatorios/ativos/pdf/", "/ativos/", "/sair"):
            with self.subTest(rota=rota):
                resposta = self.client.get(rota)
                self.assertEqual(resposta.status_code, 302)
                self.assertTrue(resposta.url.startswith(reverse("contas:senha")))
        antes = Usuario.objects.count()
        resposta = self.client.post(reverse("contas:criar"), self.dados(username="proibido"))
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Usuario.objects.count(), antes)
        self.assertEqual(self.client.get(reverse("contas:senha")).status_code, 200)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_troca_http_preserva_sessao_libera_acesso_e_descarta_next_externo(self):
        pessoa = self.novo()
        self.assertTrue(self.client.login(username=pessoa.username, password=TEMP))
        resposta = self.client.post(reverse("contas:senha"), {"old_password": TEMP, "new_password1": PESSOAL,
            "new_password2": PESSOAL, "next": "https://outro.example/"})
        self.assertRedirects(resposta, reverse("inicio"))
        self.assertEqual(int(self.client.session[SESSION_KEY]), pessoa.pk)
        self.assertEqual(self.client.get(reverse("inicio")).status_code, 200)

    def test_troca_http_nao_confirma_senhas_divergentes_e_revalida_senha_sob_lock(self):
        pessoa = self.novo()
        self.client.force_login(pessoa)
        resposta = self.client.post(reverse("contas:senha"), {"old_password": TEMP, "new_password1": PESSOAL,
            "new_password2": "divergente"})
        self.assertEqual(resposta.status_code, 200)
        pessoa.refresh_from_db()
        self.assertTrue(pessoa.check_password(TEMP) and pessoa.deve_trocar_senha)
        with patch("contas.views.services.trocar_senha", side_effect=ValidationError({"old_password": "A senha mudou."})):
            self.assertContains(self.client.post(reverse("contas:senha"), {"old_password": TEMP,
                "new_password1": PESSOAL, "new_password2": PESSOAL}), "A senha mudou.")

    def test_acesso_http_somente_admin_sem_autoatribuicao_de_perfil(self):
        self.client.force_login(self.ti)
        for rota in (reverse("contas:listar"), reverse("contas:criar"), reverse("contas:editar", args=[self.ti.pk]),
                     reverse("contas:redefinir", args=[self.admin.pk])):
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 403)
                self.assertEqual(self.client.post(rota, {"perfil": "administrador"}).status_code, 403)
        self.ti.refresh_from_db()
        self.assertFalse(self.ti.administrador_ti)

    def test_admin_do_gestati_gerencia_contas_sem_acesso_ao_admin_tecnico(self):
        gestor = Usuario.objects.create_user("gestor_ti", administrador_ti=True)
        self.client.force_login(gestor)
        self.assertEqual(self.client.get(reverse("contas:listar")).status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        r = self.client.post(reverse("contas:criar"), {**self.dados(), "senha_temporaria": TEMP, "confirmar_senha": TEMP,
            "is_staff": "on", "is_superuser": "on"})
        self.assertRedirects(r, reverse("contas:listar"))
        pessoa = Usuario.objects.get(username="novotecnico")
        self.assertFalse(pessoa.is_superuser or pessoa.is_staff)

    def test_admin_ti_nao_pode_assumir_conta_tecnica_por_edicao_ou_redefinicao(self):
        gestor = Usuario.objects.create_user("gestor_limitado", administrador_ti=True)
        self.client.force_login(gestor)
        for nome in ("editar", "redefinir"):
            rota = reverse("contas:"+nome, args=[self.admin.pk])
            self.assertEqual(self.client.get(rota).status_code, 403)
            self.assertEqual(self.client.post(rota, {}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            redefinir_senha(autor=gestor, usuario_id=self.admin.pk, versao=1, senha_temporaria=TEMP)
        with self.assertRaises(PermissionDenied):
            salvar_usuario(autor=gestor, usuario_id=self.admin.pk, versao=1,
                dados=self.dados(username="gestor", perfil="administrador"))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("Gestor!48-local"))

    def test_formularios_listagem_filtros_edicao_e_redefinicao(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("contas:listar")+"?q=tecnico"), "Técnico")
        self.assertNotContains(self.client.get(reverse("contas:listar")+"?situacao=inativos"), "tecnico")
        for nome, args in (("criar", []), ("editar", [self.ti.pk]), ("redefinir", [self.ti.pk])):
            r = self.client.get(reverse("contas:"+nome, args=args))
            self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("contas:editar", args=[self.ti.pk]), self.dados(username="tecnico", versao=1))
        self.assertRedirects(r, reverse("contas:listar"))
        self.ti.refresh_from_db()
        r = self.client.post(reverse("contas:redefinir", args=[self.ti.pk]), {"versao": self.ti.versao_acesso,
            "senha_temporaria": TEMP, "confirmar_senha": TEMP})
        self.assertRedirects(r, reverse("contas:listar"))

    def test_csrf_e_metodos_em_credenciais_e_usuarios(self):
        seguro = Client(enforce_csrf_checks=True)
        seguro.force_login(self.admin)
        for rota in (reverse("contas:criar"), reverse("contas:senha"), reverse("contas:redefinir", args=[self.ti.pk]), reverse("logout")):
            self.assertEqual(seguro.post(rota, {}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.put(reverse("contas:criar")).status_code, 405)

    def test_admin_tecnico_nao_contorna_servicos_de_contas(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/admin/contas/usuario/add/").status_code, 403)
        self.assertEqual(self.client.post(f"/admin/contas/usuario/{self.ti.pk}/change/", {}).status_code, 403)
        self.assertEqual(self.client.post(f"/admin/contas/usuario/{self.ti.pk}/delete/", {}).status_code, 403)

    def test_falha_na_gravacao_reverte_toda_a_alteracao(self):
        with patch.object(Usuario, "save", side_effect=RuntimeError("falha simulada")):
            with self.assertRaises(RuntimeError):
                salvar_usuario(autor=self.admin, usuario_id=self.ti.pk, versao=1, dados=self.dados(username="tecnico", ativo=False))
        self.ti.refresh_from_db()
        self.assertTrue(self.ti.is_active)
        self.assertEqual(self.ti.versao_acesso, 1)


class ConcorrenciaContasTests(TransactionTestCase):
    def test_administradores_nao_podem_inativar_um_ao_outro_simultaneamente(self):
        a = Usuario.objects.create_user("gestor_a", administrador_ti=True)
        b = Usuario.objects.create_user("gestor_b", administrador_ti=True)
        barreira = Barrier(2)
        def executar(autor, alvo):
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                salvar_usuario(autor=autor, usuario_id=alvo.pk, versao=1,
                    dados={"nome": "Gestor", "username": alvo.username, "perfil": "administrador", "ativo": False})
                return "ok"
            except (PermissionDenied, ValidationError):
                return "recusado"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa, fb = pool.submit(executar, a, b), pool.submit(executar, b, a)
            resultados = [fa.result(timeout=25), fb.result(timeout=25)]
        self.assertCountEqual(resultados, ["ok", "recusado"])
        self.assertEqual(Usuario.objects.filter(administrador_ti=True, is_active=True).count(), 1)

    def test_cadastros_concorrentes_com_usuario_igual_nao_duplicam(self):
        a = Usuario.objects.create_user("gestor_a", administrador_ti=True)
        b = Usuario.objects.create_user("gestor_b", administrador_ti=True)
        barreira = Barrier(2)
        def executar(ator, username):
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                salvar_usuario(autor=ator, dados={"nome": "Pessoa", "username": username, "perfil": "ti", "ativo": True}, senha_temporaria=TEMP)
                return "ok"
            except ValidationError:
                return "recusado"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa, fb = pool.submit(executar, a, "Duplicado"), pool.submit(executar, b, "duplicado")
            resultados = [fa.result(timeout=25), fb.result(timeout=25)]
        self.assertCountEqual(resultados, ["ok", "recusado"])
        self.assertEqual(Usuario.objects.filter(username__iexact="duplicado").count(), 1)
