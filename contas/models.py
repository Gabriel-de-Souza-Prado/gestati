from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    """Conta da TI com autenticação e permissões nativas do Django."""

    administrador_ti = models.BooleanField("administrador da TI", default=False)
    deve_trocar_senha = models.BooleanField("troca de senha obrigatória", default=False)
    versao_acesso = models.PositiveIntegerField(default=1, editable=False)

    @property
    def gerencia_usuarios(self):
        return self.is_active and (self.is_superuser or self.administrador_ti)

    @property
    def perfil_exibicao(self):
        return "Administrador" if self.is_superuser or self.administrador_ti else "Usuário da TI"

    class Meta:
        verbose_name = "usuário da TI"
        verbose_name_plural = "usuários da TI"

    def __str__(self):
        return self.get_full_name() or self.username
