from django.urls import path
from . import views

app_name = "contas"
urlpatterns = [
    path("usuarios/", views.listar, name="listar"),
    path("usuarios/novo/", views.criar, name="criar"),
    path("usuarios/<int:pk>/editar/", views.editar, name="editar"),
    path("usuarios/<int:pk>/senha/", views.redefinir, name="redefinir"),
    path("minha-conta/senha/", views.senha, name="senha"),
]
