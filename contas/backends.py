"""Login por nome de usuário sem diferenciar maiúsculas de minúsculas."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied
from django.views.decorators.debug import sensitive_variables


class UsuarioSemDiferencaDeCaixaBackend(ModelBackend):
    @sensitive_variables("password")
    def authenticate(self, request, username=None, password=None, **kwargs):
        modelo = get_user_model()
        if username is None:
            username = kwargs.get(modelo.USERNAME_FIELD)
        if username is None or password is None:
            return None
        candidatos = list(modelo._default_manager.filter(username__iexact=username)[:2])
        if len(candidatos) == 1:
            usuario = candidatos[0]
            if usuario.check_password(password) and self.user_can_authenticate(usuario):
                return usuario
        else:
            # Mesmo trabalho de hash quando não há conta única identificável.
            modelo().set_password(password)
        # Não cair no backend sensível a caixa quando o login é inválido/ambíguo.
        # Ele permanece configurado somente para ler sessões anteriores à revisão.
        raise PermissionDenied
