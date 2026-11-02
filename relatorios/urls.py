from django.urls import path
from . import views

app_name = "relatorios"
urlpatterns = [
    path("relatorios/", views.inicio, name="inicio"),
    path("relatorios/<slug:tipo>/pdf/", views.consultar_relatorio, {"pdf": True}, name="imprimir"),
    path("relatorios/<slug:tipo>/", views.consultar_relatorio, name="consultar"),
]
