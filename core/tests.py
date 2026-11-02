from django.test import Client, SimpleTestCase
from django.urls import reverse
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os

from .templatetags.recursos import recurso


class ProtecaoDeAcessoTests(SimpleTestCase):
    """A barreira de acesso não depende de um banco de teste."""

    def test_pagina_interna_exige_login(self):
        response = self.client.get(reverse("inicio"))
        self.assertRedirects(
            response, f"{reverse('login')}?next=/", fetch_redirect_response=False
        )

    def test_login_rejeita_post_sem_csrf(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse("login"), {"username": "teste", "password": "nao-e-uma-credencial"}
        )
        self.assertEqual(response.status_code, 403)

    def test_recurso_muda_url_automaticamente_quando_arquivo_e_atualizado(self):
        with TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "teste.css"
            arquivo.write_text("body{color:black}", encoding="utf-8")
            with patch("core.templatetags.recursos.finders.find", return_value=str(arquivo)):
                antes = recurso("css/teste.css")
                instante = arquivo.stat().st_mtime_ns
                arquivo.write_text("body{color:green}", encoding="utf-8")
                os.utime(arquivo, ns=(instante + 1000000, instante + 1000000))
                depois = recurso("css/teste.css")
            self.assertNotEqual(antes, depois)
            self.assertTrue(antes.startswith("/static/css/teste.css?v="))
            self.assertTrue(depois.startswith("/static/css/teste.css?v="))
