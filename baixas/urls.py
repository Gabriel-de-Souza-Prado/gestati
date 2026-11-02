from django.urls import path
from . import views

app_name = "baixas"
urlpatterns = [
    path("baixas/", views.listar, name="listar"),
    path("baixas/nova/", views.selecionar, name="selecionar"),
    path("baixas/nova/<int:ativo_pk>/", views.registrar, name="registrar"),
    path("baixas/<int:pk>/", views.detalhar, name="detalhar"),
    path("baixas/<int:pk>/pdf/", views.imprimir, name="imprimir"),
]
