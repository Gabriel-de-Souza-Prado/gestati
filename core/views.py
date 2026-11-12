from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@login_required
def inicio(request):
    from relatorios.selectors import pendencias_operacionais
    return render(request, "core/inicio.html", {"pendencias": pendencias_operacionais()})


@require_safe
@never_cache
def health(request):
    """Disponibilidade da aplicação/banco sem divulgar configuração ou dados."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "indisponivel"}, status=503)
    return JsonResponse({"status": "ok"})
