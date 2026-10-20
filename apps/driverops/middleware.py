from django.conf import settings
from django.http import HttpResponseForbidden
from django.db import transaction
from django.utils.cache import add_never_cache_headers
from apps.fleet.tenant_scope import Scope, set_scope, reset_scope
from .models import Member


class CompanyBoundaryMiddleware:
    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        user=request.user
        scope=Scope(blocked=True)
        member=None
        if user.is_authenticated:
            if user.is_superuser:
                scope=None
            else:
                member=Member.objects.filter(user=user,active=True,company__active=True).select_related('company').first()
                if member:
                    scope=Scope(company_id=member.company_id,actor_id=user.pk)
        request.central_user_management = getattr(settings, "CENTRAL_USER_MANAGEMENT", False)
        request.company_mode=True
        request.company_member=member
        request.company=member.company if member else None
        request.company_manager=bool(member and member.role=='manager')
        token=set_scope(scope)
        try:
            common=('/entrar/','/sair/','/logout/','/minha-senha/','/static/')
            if not user.is_superuser:
                if request.path.startswith(('/admin/','/perfis/','/api/sync/','/media/')) or (request.path.startswith('/usuarios/') and not (getattr(settings, 'CENTRAL_USER_MANAGEMENT', False) and member and member.role == Member.MANAGER)):
                    return HttpResponseForbidden('Acesso exclusivo à administração da plataforma.')
                if user.is_authenticated and not member and not request.path.startswith(common):
                    return HttpResponseForbidden('Usuário sem empresa ativa.')
                if member and member.role=='driver' and not request.path.startswith(('/api/driver/',*common)):
                    return HttpResponseForbidden('Use o aplicativo do motorista.')
            response=self.get_response(request)
            if member:
                if "no-store" not in response.get("Cache-Control", ""):
                    add_never_cache_headers(response)
            return response
        finally:
            reset_scope(token)
