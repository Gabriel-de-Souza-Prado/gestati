from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def inicio(request):
    from relatorios.selectors import pendencias_operacionais
    return render(request, "core/inicio.html", {"pendencias": pendencias_operacionais()})
