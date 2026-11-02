from urllib.parse import urlencode
from django.shortcuts import redirect
from django.urls import reverse


class TrocaSenhaObrigatoriaMiddleware:
    """Abrange também URLs diretas, admin, PDFs e requisições de escrita."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.user.deve_trocar_senha:
            permitidas = {reverse("contas:senha"), reverse("logout")}
            if request.path not in permitidas:
                destino = request.get_full_path() if request.method == "GET" else reverse("inicio")
                return redirect(reverse("contas:senha") + "?" + urlencode({"next": destino}))
        return self.get_response(request)
