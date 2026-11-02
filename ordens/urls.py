from django.urls import path
from . import views

app_name = "ordens"
urlpatterns = [
    path("ordens/", views.listar, name="listar"),
    path("ordens/nova/", views.selecionar_ativo, name="selecionar_ativo"),
    path("ordens/nova/<int:ativo_pk>/", views.abrir, name="abrir"),
    path("ordens/<int:pk>/", views.detalhar, name="detalhar"),
    path("ordens/<int:pk>/servicos/<int:registro_pk>/editar/", views.servico_editar, name="servico_editar"),
    path("ordens/<int:pk>/pdf/", views.imprimir, name="imprimir"),
    path("ordens/<int:pk>/<str:acao>/", views.operar, name="operar"),
]
