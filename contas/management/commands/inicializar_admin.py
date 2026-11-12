"""Primeira conta da hospedagem sem terminal remoto e sem senha no código."""
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.views.decorators.debug import sensitive_variables


class Command(BaseCommand):
    help = "Cria a primeira conta técnica somente quando solicitado e o banco ainda não possui usuários."

    @sensitive_variables("senha", "usuario")
    def handle(self, *args, **options):
        if os.environ.get("GESTATI_BOOTSTRAP_ADMIN") != "1":
            self.stdout.write("Inicialização administrativa não solicitada.")
            return
        modelo = get_user_model()
        with transaction.atomic():
            # Serializa também a primeira criação, quando ainda não há linhas.
            tabela = connection.ops.quote_name(modelo._meta.db_table)
            with connection.cursor() as cursor:
                cursor.execute(f"LOCK TABLE {tabela} IN SHARE ROW EXCLUSIVE MODE")
            if modelo.objects.exists():
                self.stdout.write("O banco já possui usuários. Nenhuma conta ou senha foi alterada.")
                return
            nome = os.environ.get("GESTATI_ADMIN_USERNAME", "").strip()
            senha = os.environ.get("GESTATI_ADMIN_PASSWORD", "")
            if not nome or not senha:
                raise CommandError("Defina GESTATI_ADMIN_USERNAME e GESTATI_ADMIN_PASSWORD no painel para a primeira inicialização.")
            usuario = modelo(username=nome, first_name="Administrador", is_staff=True, is_superuser=True, deve_trocar_senha=True)
            try:
                validate_password(senha, user=usuario)
                usuario.set_password(senha)
                usuario.full_clean()
            except ValidationError as erro:
                raise CommandError("Não foi possível criar a primeira conta: " + " ".join(erro.messages)) from None
            usuario.save()
        self.stdout.write(self.style.SUCCESS("Primeira conta criada. A troca da senha temporária será exigida ao entrar."))
