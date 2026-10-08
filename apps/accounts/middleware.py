from django.shortcuts import redirect


class ForcePasswordChangeMiddleware:
    def process_view(self, request, view_func, view_args, view_kwargs):
        return OperationalInspectionMiddleware(
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


def is_inspection_only(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_system_creator or user.is_superuser:
        return False
    if user.groups.filter(name="Administrador ADM").exists():
        return False
    return user.groups.filter(name="Operacional").exists()


class OperationalInspectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from django.core.exceptions import PermissionDenied

        request.inspection_only = is_inspection_only(request.user)
        if not request.inspection_only:
            return None

        match = request.resolver_match
        name = match.url_name if match else None
        namespace = match.namespace if match else ""
        allowed = {
            "login", "logout", "password_change",
            "inspection_list", "inspection_create",
        }
        if not namespace and name in allowed:
            return None
        if not namespace and name == "dashboard":
            return redirect("inspection_list")
        raise PermissionDenied(
            "Seu perfil permite acesso somente à seção Vistorias."
        )
