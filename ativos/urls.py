from django.urls import path
from . import views

app_name = "ativos"
urlpatterns = [
    path("ativos/", views.ativo_listar, name="ativo_listar"),
    path("ativos/novo/", views.ativo_criar, name="ativo_criar"),
    path("ativos/catalogo-componentes/", views.catalogo_componentes, name="catalogo_componentes"),
    path("ativos/especificacoes/nova/", views.especificacao_criar, name="especificacao_criar"),
    path("ativos/<int:pk>/configuracao/", views.configuracao_alterar, name="configuracao_alterar"),
    path("ativos/<int:pk>/", views.ativo_detalhar, name="ativo_detalhar"),
    path("ativos/<int:pk>/editar/", views.ativo_editar, name="ativo_editar"),
]
