"""Two hostnames, one backend and one authoritative account/fleet database."""
from urllib.parse import urlsplit
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect


def management_url(path='/'):
    return settings.MANAGEMENT_ORIGIN.rstrip('/') + path


def app_url():
    return settings.DRIVER_APP_ORIGIN.rstrip('/') + '/api/driver/app/'


class AppSurfaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.driver_app_surface = request.get_host().lower() == urlsplit(settings.DRIVER_APP_ORIGIN).netloc.lower()
        if request.driver_app_surface:
            if request.path == '/':
                return redirect('/api/driver/app/')
            target = None
            if request.path.startswith(('/api/driver/management/', '/empresas/')):
                target = '/empresas/' if request.user.is_superuser else '/usuarios/'
            elif request.path.startswith('/api/driver/panel/'):
                target = '/gestao/bdts/'
            elif not request.path.startswith(('/api/driver/', '/entrar/', '/sair/', '/minha-senha/', '/static/')):
                target = request.path
            if target is not None:
                url = management_url(target)
                if request.method not in ('GET', 'HEAD'):
                    return JsonResponse({'detail': 'Gerencie os acessos no sistema principal.', 'management_url': url}, status=409)
                return redirect(url)
        return self.get_response(request)
