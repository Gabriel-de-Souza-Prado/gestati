from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from contas.forms import LoginAdministrativoForm, LoginForm

admin.site.site_header = "Administração do GESTATI"
admin.site.site_title = "GESTATI"
admin.site.index_title = "Administração"
admin.site.login_form = LoginAdministrativoForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "entrar/",
        auth_views.LoginView.as_view(redirect_authenticated_user=True, authentication_form=LoginForm),
        name="login",
    ),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("cadastros.urls")),
    path("", include("estoque.urls")),
    path("", include("ativos.urls")),
    path("", include("ordens.urls")),
    path("", include("movimentacoes.urls")),
    path("", include("baixas.urls")),
    path("", include("relatorios.urls")),
    path("", include("core.urls")),
    path("", include("contas.urls")),
]
