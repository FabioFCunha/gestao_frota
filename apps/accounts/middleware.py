from django.shortcuts import redirect


class ForcePasswordChangeMiddleware:
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
