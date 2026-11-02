from django.urls import path

from . import views

app_name = "cadastros"
urlpatterns = [
    path("categorias/", views.categoria_listar, name="categoria_listar"),
    path("categorias/nova/", views.categoria_criar, name="categoria_criar"),
    path("categorias/iniciais/", views.categoria_iniciais, name="categoria_iniciais"),
    path("categorias/<int:pk>/editar/", views.categoria_editar, name="categoria_editar"),
    path("categorias/<int:pk>/situacao/", views.categoria_situacao, name="categoria_situacao"),
    path("categorias/<int:pk>/excluir/", views.categoria_excluir, name="categoria_excluir"),
    path("fornecedores/", views.fornecedor_listar, name="fornecedor_listar"),
    path("fornecedores/novo/", views.fornecedor_criar, name="fornecedor_criar"),
    path("fornecedores/<int:pk>/editar/", views.fornecedor_editar, name="fornecedor_editar"),
    path("fornecedores/<int:pk>/situacao/", views.fornecedor_situacao, name="fornecedor_situacao"),
    path("fornecedores/<int:pk>/excluir/", views.fornecedor_excluir, name="fornecedor_excluir"),
    path("departamentos/", views.departamento_listar, name="departamento_listar"),
    path("departamentos/novo/", views.departamento_criar, name="departamento_criar"),
    path("departamentos/<int:pk>/editar/", views.departamento_editar, name="departamento_editar"),
    path("departamentos/<int:pk>/situacao/", views.departamento_situacao, name="departamento_situacao"),
    path("departamentos/<int:pk>/excluir/", views.departamento_excluir, name="departamento_excluir"),
]
