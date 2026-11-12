import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase
from django.urls import reverse


class HospedagemTests(SimpleTestCase):
    def ambiente(self, **mudancas):
        ambiente = {k: v for k, v in os.environ.items() if not k.startswith(("GESTATI_", "DJANGO_", "RENDER_")) and k != "DATABASE_URL"}
        ambiente.update({
            "PYTHONIOENCODING": "utf-8",
            "GESTATI_SECRET_KEY": "chave-apenas-de-teste-abcdefghijklmnopqrstuvwxyz-0123456789-9876543210",
            "DATABASE_URL": "postgresql://usuario_ficticio:nao-e-credencial@127.0.0.1:55432/gestati_qa",
            "RENDER_EXTERNAL_HOSTNAME": "gestati-demo.onrender.com",
        })
        for k, v in mudancas.items():
            if v is None:
                ambiente.pop(k, None)
            else:
                ambiente[k] = v
        return ambiente

    def ler_producao(self, **mudancas):
        programa = """
import json
from config import settings_production as s
print(json.dumps({'debug':s.DEBUG,'hosts':s.ALLOWED_HOSTS,'origins':s.CSRF_TRUSTED_ORIGINS,
'engine':s.DATABASES['default']['ENGINE'],'name':s.DATABASES['default']['NAME'],
'secure':s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE and s.SECURE_SSL_REDIRECT,
'storage':s.STORAGES['staticfiles']['BACKEND'],'middleware':s.MIDDLEWARE[1]}))
"""
        return subprocess.run([sys.executable, "-c", programa], cwd=Path(__file__).resolve().parent.parent,
            env=self.ambiente(**mudancas), capture_output=True, text=True, encoding="utf-8")

    def test_producao_usa_postgres_remoto_https_estaticos_e_debug_desligado(self):
        resultado = self.ler_producao(GESTATI_DEBUG="true")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        dados = json.loads(resultado.stdout)
        self.assertFalse(dados["debug"])
        self.assertTrue(dados["secure"])
        self.assertEqual(dados["hosts"], ["gestati-demo.onrender.com"])
        self.assertEqual(dados["origins"], ["https://gestati-demo.onrender.com"])
        self.assertEqual(dados["engine"], "django.db.backends.postgresql")
        self.assertEqual(dados["name"], "gestati_qa")
        self.assertIn("CompressedManifest", dados["storage"])
        self.assertEqual(dados["middleware"], "whitenoise.middleware.WhiteNoiseMiddleware")

    def test_producao_nao_reutiliza_banco_ou_chave_local_ao_faltar_variavel(self):
        for variavel in ("GESTATI_SECRET_KEY", "DATABASE_URL", "RENDER_EXTERNAL_HOSTNAME"):
            with self.subTest(variavel=variavel):
                resultado = self.ler_producao(**{variavel: None})
                self.assertNotEqual(resultado.returncode, 0)
                self.assertIn("ImproperlyConfigured", resultado.stderr)

    def test_producao_rejeita_sqlite_host_coringa_e_url_invalida_sem_revelar_url(self):
        for mudancas in ({"DATABASE_URL": "sqlite:///:memory:"}, {"GESTATI_ALLOWED_HOSTS": "*"},
                {"DATABASE_URL": "url-invalida-com-segredo-ficticio"}):
            with self.subTest(campos=list(mudancas)):
                resultado = self.ler_producao(**mudancas)
                self.assertNotEqual(resultado.returncode, 0)
                self.assertIn("ImproperlyConfigured", resultado.stderr)
                self.assertNotIn("url-invalida-com-segredo-ficticio", resultado.stderr)

    def test_dominio_adicional_e_render_sao_preservados_sem_duplicar(self):
        resultado = self.ler_producao(GESTATI_ALLOWED_HOSTS="demo.exemplo.org,gestati-demo.onrender.com")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(json.loads(resultado.stdout)["hosts"], ["demo.exemplo.org", "gestati-demo.onrender.com"])

    def test_health_publico_so_consulta_disponibilidade_sem_dados(self):
        with patch("core.views.connection") as banco:
            resposta = self.client.get(reverse("health"))
            self.assertEqual(resposta.status_code, 200)
            self.assertEqual(resposta.json(), {"status": "ok"})
            banco.cursor.return_value.__enter__.return_value.execute.assert_called_once_with("SELECT 1")
        self.assertIn("no-store", resposta["Cache-Control"])

    def test_health_falha_no_banco_retorna_503_sem_detalhes(self):
        with patch("core.views.connection") as banco:
            banco.cursor.side_effect = OperationalError("detalhe privado do banco")
            resposta = self.client.get(reverse("health"))
        self.assertEqual(resposta.status_code, 503)
        self.assertEqual(resposta.json(), {"status": "indisponivel"})
        self.assertNotContains(resposta, "detalhe privado", status_code=503)
        self.assertEqual(self.client.post(reverse("health"), {}).status_code, 405)
