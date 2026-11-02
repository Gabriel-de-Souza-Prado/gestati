from django.urls import path

from . import views

app_name = "estoque"
urlpatterns = [
    path("componentes/", views.componente_listar, name="componente_listar"),
    path("componentes/novo/", views.componente_criar, name="componente_criar"),
    path("componentes/<int:pk>/", views.componente_detalhar, name="componente_detalhar"),
    path("componentes/<int:pk>/editar/", views.componente_editar, name="componente_editar"),
    path("componentes/<int:pk>/situacao/", views.componente_situacao, name="componente_situacao"),
    path("componentes/<int:pk>/excluir/", views.componente_excluir, name="componente_excluir"),
    path("estoque/entradas/nova/", views.entrada_criar, name="entrada_criar"),
]
