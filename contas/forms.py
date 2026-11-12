from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.password_validation import password_validators_help_text_html
from django.contrib.auth.validators import UnicodeUsernameValidator
from .models import Usuario


class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Informe um usuário e uma senha corretos. A senha diferencia letras maiúsculas de minúsculas.",
    }


class LoginAdministrativoForm(AdminAuthenticationForm):
    error_messages = {
        **AdminAuthenticationForm.error_messages,
        "invalid_login": "Informe usuário e senha de uma conta com acesso à administração técnica. A senha diferencia letras maiúsculas de minúsculas.",
    }


class DadosUsuarioForm(forms.Form):
    nome = forms.CharField(label="Nome", max_length=150)
    sobrenome = forms.CharField(label="Sobrenome", max_length=150, required=False)
    username = forms.CharField(label="Usuário", max_length=150, validators=[UnicodeUsernameValidator()],
        help_text="Usado para entrar no GESTATI. Letras, números e @ . + - _.")
    email = forms.EmailField(label="E-mail", required=False)
    perfil = forms.ChoiceField(label="Perfil", choices=[("ti", "Usuário da TI"), ("administrador", "Administrador")],
        help_text="Administrador também gerencia as contas de acesso.")
    ativo = forms.BooleanField(label="Conta ativa", required=False, initial=True)
    versao = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, usuario=None, **kwargs):
        if usuario is not None:
            kwargs["initial"] = {"nome": usuario.first_name, "sobrenome": usuario.last_name, "username": usuario.username,
                "email": usuario.email, "perfil": "administrador" if usuario.is_superuser or usuario.administrador_ti else "ti",
                "ativo": usuario.is_active, "versao": usuario.versao_acesso}
        super().__init__(*args, **kwargs)
        if usuario is not None and usuario.is_superuser:
            self.fields["perfil"].disabled = True
            self.fields["perfil"].help_text = "Perfil da conta técnica inicial preservado."


class SenhaTemporariaForm(forms.Form):
    senha_temporaria = forms.CharField(label="Senha temporária", strip=False, max_length=4096,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}), help_text=password_validators_help_text_html())
    confirmar_senha = forms.CharField(label="Confirme a senha temporária", strip=False, max_length=4096,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean(self):
        dados = super().clean()
        if dados.get("senha_temporaria") != dados.get("confirmar_senha"):
            self.add_error("confirmar_senha", "As senhas não conferem.")
        return dados


class NovoUsuarioForm(DadosUsuarioForm, SenhaTemporariaForm):
    field_order = ["nome", "sobrenome", "username", "email", "perfil", "ativo", "senha_temporaria", "confirmar_senha", "versao"]


class RedefinirSenhaForm(SenhaTemporariaForm):
    versao = forms.IntegerField(widget=forms.HiddenInput)


class SenhaPessoalForm(PasswordChangeForm):
    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["old_password"].label = "Senha temporária" if user.deve_trocar_senha else "Senha atual"

    def clean(self):
        dados = super().clean()
        senha = dados.get("new_password2")
        if senha and self.user.check_password(senha):
            self.add_error("new_password2", "Escolha uma senha diferente da atual.")
        return dados
