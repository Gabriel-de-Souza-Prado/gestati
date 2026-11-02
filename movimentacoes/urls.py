from django.urls import path
from . import views

app_name = "movimentacoes"
urlpatterns = [
    path("movimentacoes/", views.listar, name="listar"),
    path("movimentacoes/<str:tipo>/novo/", views.selecionar, name="selecionar"),
    path("movimentacoes/<str:tipo>/novo/<int:ativo_pk>/", views.registrar, name="registrar"),
    path("movimentacoes/transferencias/<int:pk>/pdf/", views.imprimir_transferencia, name="imprimir"),
    path("movimentacoes/emprestimos/<int:pk>/devolver/", views.devolver, name="devolver"),
    path("movimentacoes/<str:tipo>/<int:pk>/", views.detalhar, name="detalhar"),
]
