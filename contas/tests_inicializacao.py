from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import os
from threading import Barrier
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase

from .models import Usuario


AMBIENTE_DEMO = {"GESTATI_BOOTSTRAP_ADMIN": "1", "GESTATI_ADMIN_USERNAME": "Admin.Demo",
    "GESTATI_ADMIN_PASSWORD": "Demonstracao!84-Provisorio"}


class InicializacaoTests(TestCase):
    def executar(self, ambiente):
        saida = StringIO()
        with patch.dict(os.environ, ambiente):
            call_command("inicializar_admin", stdout=saida)
        return saida.getvalue()

    def test_so_inicializa_quando_explicitamente_habilitado(self):
        self.executar({"GESTATI_BOOTSTRAP_ADMIN": ""})
        self.assertFalse(Usuario.objects.exists())

    def test_primeira_conta_tem_hash_permissao_tecnica_e_troca_inicial(self):
        saida = self.executar(AMBIENTE_DEMO)
        usuario = Usuario.objects.get()
        self.assertEqual(usuario.username, "Admin.Demo")
        self.assertTrue(usuario.is_superuser and usuario.is_staff and usuario.deve_trocar_senha)
        self.assertTrue(usuario.check_password(AMBIENTE_DEMO["GESTATI_ADMIN_PASSWORD"]))
        self.assertNotIn(AMBIENTE_DEMO["GESTATI_ADMIN_PASSWORD"], saida)

    def test_repeticao_nao_reseta_senha_nem_eleva_usuario_existente(self):
        existente = Usuario.objects.create_user("pessoa", password="Pessoal!74-original")
        hash_anterior = existente.password
        self.executar(AMBIENTE_DEMO)
        existente.refresh_from_db()
        self.assertEqual(Usuario.objects.count(), 1)
        self.assertEqual(existente.password, hash_anterior)
        self.assertFalse(existente.is_superuser or existente.is_staff or existente.deve_trocar_senha)

    def test_pode_remover_segredos_da_inicializacao_depois_da_primeira_conta(self):
        self.executar(AMBIENTE_DEMO)
        anterior = Usuario.objects.get().password
        self.executar({"GESTATI_BOOTSTRAP_ADMIN": "1", "GESTATI_ADMIN_USERNAME": "", "GESTATI_ADMIN_PASSWORD": ""})
        self.assertEqual(Usuario.objects.get().password, anterior)

    def test_senha_fraca_username_invalido_ou_ausencia_nao_criam_conta(self):
        for alteracao in ({"GESTATI_ADMIN_PASSWORD": "123"}, {"GESTATI_ADMIN_USERNAME": "nome com espaço"},
                {"GESTATI_ADMIN_PASSWORD": ""}, {"GESTATI_ADMIN_USERNAME": ""}):
            with self.subTest(campos=list(alteracao)), self.assertRaises(CommandError):
                self.executar({**AMBIENTE_DEMO, **alteracao})
            self.assertFalse(Usuario.objects.exists())


class InicializacaoConcorrenteTests(TransactionTestCase):
    def test_duas_inicializacoes_criam_uma_unica_conta(self):
        barreira = Barrier(2)
        def inicializar():
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                call_command("inicializar_admin", stdout=StringIO())
            finally:
                close_old_connections()
        with patch.dict(os.environ, AMBIENTE_DEMO), ThreadPoolExecutor(max_workers=2) as executor:
            resultados = [executor.submit(inicializar) for _ in range(2)]
            for resultado in resultados:
                resultado.result(timeout=20)
        self.assertEqual(Usuario.objects.count(), 1)
