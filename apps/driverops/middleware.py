from django.http import HttpResponseForbidden
from .models import Member


class CompanyBoundaryMiddleware:
    """Accounts assigned to the new company module cannot enter unscoped legacy views."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not user.is_superuser and Member.objects.filter(user=user).exists():
            allowed = (
                "/api/driver/", "/entrar/", "/sair/", "/logout/",
                "/minha-senha/", "/static/",
            )
            if not request.path.startswith(allowed):
                return HttpResponseForbidden("Este usuário acessa somente o módulo da sua empresa.")
        return self.get_response(request)
