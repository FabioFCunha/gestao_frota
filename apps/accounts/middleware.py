from django.shortcuts import redirect


class ForcePasswordChangeMiddleware:
    def process_view(self, request, view_func, view_args, view_kwargs):
        return LegacyOperationalAccessMiddleware(
            self.get_response
        ).process_view(request, view_func, view_args, view_kwargs)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if (
            user is not None
            and user.is_authenticated
            and user.must_change_password
            and request.path not in {"/minha-senha/", "/sair/"}
            and not request.path.startswith("/static/")
            and not request.path.startswith("/media/")
            and not request.path.startswith("/admin/")
        ):
            return redirect("password_change")

        return self.get_response(request)


def is_legacy_operational(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_system_creator or user.is_superuser:
        return False
    if user.groups.filter(name="Administrador ADM").exists():
        return False
    return user.groups.filter(name="Operacional").exists()


class LegacyOperationalAccessMiddleware:
    """Keep former inspection-only accounts restricted until their role is reassigned."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from django.core.exceptions import PermissionDenied

        from django.conf import settings
        if getattr(settings, 'CENTRAL_USER_MANAGEMENT', False) and getattr(request, 'company_member', None):
            return None
        if not is_legacy_operational(request.user):
            return None

        match = request.resolver_match
        name = match.url_name if match else None
        namespace = match.namespace if match else ""
        allowed = {
            "login", "logout", "password_change",
        }
        if not namespace and name in allowed:
            return None
        raise PermissionDenied(
            "Solicite ao gestor a atualização do seu perfil de acesso."
        )
