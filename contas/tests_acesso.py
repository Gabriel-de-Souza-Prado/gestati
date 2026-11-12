from unittest.mock import patch

from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from .models import Usuario
from .services import trocar_senha


class RevisaoAcessoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user("Ti.teste", password="Teste!82-Acesso", first_name="Pessoa")
        cls.admin = Usuario.objects.create_superuser("gestor_tema", password="Gestor!82-Acesso")

    def test_login_aceita_variacoes_de_caixa_sem_renomear_conta(self):
        for nome in ("ti.teste", "TI.TESTE", "Ti.tEsTe"):
            with self.subTest(nome=nome):
                cliente = Client()
                resposta = cliente.post(reverse("login"), {"username": nome, "password": "Teste!82-Acesso"})
                self.assertRedirects(resposta, reverse("inicio"))
                self.assertEqual(int(cliente.session["_auth_user_id"]), self.usuario.pk)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.username, "Ti.teste")

    def test_senha_diferencia_caixa_e_conta_inativa_nao_entra(self):
        self.assertIsNone(authenticate(username="ti.teste", password="teste!82-acesso"))
        Usuario.objects.filter(pk=self.usuario.pk).update(is_active=False)
        self.assertIsNone(authenticate(username="TI.TESTE", password="Teste!82-Acesso"))
        self.assertIsNone(authenticate(username="ausente", password="Teste!82-Acesso"))

    def test_ambiguidade_legada_nao_seleciona_conta_nem_cai_no_backend_antigo(self):
        Usuario.objects.create_user("ti.teste", password="Outra!82-Senha")
        with patch("django.contrib.auth.backends.ModelBackend.authenticate") as antigo:
            self.assertIsNone(authenticate(username="Ti.teste", password="Teste!82-Acesso"))
            antigo.assert_not_called()

    def test_sessao_anterior_continua_valida(self):
        self.client.force_login(self.usuario, backend="django.contrib.auth.backends.ModelBackend")
        self.assertEqual(self.client.get(reverse("inicio")).status_code, 200)

    def test_login_com_caixa_diferente_preserva_troca_inicial(self):
        Usuario.objects.filter(pk=self.usuario.pk).update(deve_trocar_senha=True)
        self.assertTrue(self.client.login(username="TI.TESTE", password="Teste!82-Acesso"))
        resposta = self.client.get(reverse("inicio"))
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta.url.startswith(reverse("contas:senha")))

    def test_senha_fraca_do_cadastro_aparece_no_campo_sem_gravar_conta(self):
        self.client.force_login(self.admin)
        resposta = self.client.post(reverse("contas:criar"), {
            "nome": "Nova pessoa", "username": "nova.pessoa", "perfil": "ti", "ativo": "on",
            "senha_temporaria": "123", "confirmar_senha": "123",
        })
        form = resposta.context["form"]
        self.assertIn("senha_temporaria", form.errors)
        self.assertFalse(form.non_field_errors())
        self.assertFalse(Usuario.objects.filter(username="nova.pessoa").exists())
        html = resposta.content.decode()
        self.assertLess(html.index('id="id_senha_temporaria"'), html.index('id="id_senha_temporaria_error"'))
        self.assertLess(html.index('id="id_senha_temporaria_error"'), html.index('id="id_confirmar_senha"'))

    def test_senha_fraca_do_reset_fica_no_campo_e_preserva_hash(self):
        self.client.force_login(self.admin)
        hash_anterior = self.usuario.password
        resposta = self.client.post(reverse("contas:redefinir", args=[self.usuario.pk]), {
            "versao": 1, "senha_temporaria": "123", "confirmar_senha": "123",
        })
        self.assertIn("senha_temporaria", resposta.context["form"].errors)
        self.assertFalse(resposta.context["form"].non_field_errors())
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.password, hash_anterior)

    def test_validacao_da_troca_sob_lock_indica_campo_da_nova_senha(self):
        with self.assertRaises(ValidationError) as erro:
            trocar_senha(usuario_id=self.usuario.pk, senha_atual="Teste!82-Acesso", nova_senha="123")
        self.assertIn("new_password2", erro.exception.message_dict)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("Teste!82-Acesso"))

    def test_erro_geral_do_login_fica_depois_dos_campos_antes_do_botao(self):
        resposta = self.client.post(reverse("login"), {"username": "Ti.teste", "password": "incorreta"})
        html = resposta.content.decode()
        self.assertLess(html.index('id="id_password"'), html.index('form-error-summary'))
        self.assertLess(html.index('form-error-summary'), html.index('type="submit">Entrar'))
        self.assertContains(resposta, "A senha diferencia letras maiúsculas de minúsculas.")
        self.assertNotContains(resposta, "ambos os campos diferenciam")

    def test_configuracoes_para_usuario_comum_exigem_acesso_e_primeira_troca(self):
        url = reverse("contas:configuracoes")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.usuario)
        self.assertRedirects(self.client.get(url), reverse("inicio"))
        inicio = self.client.get(reverse("inicio"))
        self.assertContains(inicio, "data-theme-toggle")
        self.assertNotContains(inicio, ">Configurações</a>")
        self.assertEqual(self.client.post(url, {}).status_code, 405)
        Usuario.objects.filter(pk=self.usuario.pk).update(deve_trocar_senha=True)
        self.assertTrue(self.client.get(url).url.startswith(reverse("contas:senha")))
