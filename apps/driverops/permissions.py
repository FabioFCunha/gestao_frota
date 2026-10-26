from rest_framework.permissions import IsAuthenticated, SAFE_METHODS
from django.conf import settings
from apps.fleet.tenant_scope import Scope, set_scope
from .models import Member


class CompanyAuthenticated(IsAuthenticated):
    def has_permission(self,request,view):
        if not super().has_permission(request,view):
            return False
        if request.user.is_superuser:
            set_scope(None)
            return True
        roles = Member.DESKTOP_ROLES if getattr(settings, 'CENTRAL_USER_MANAGEMENT', False) else (Member.MANAGER,)
        member=Member.objects.filter(user=request.user,active=True,company__active=True,role__in=roles).first()
        if not member:
            return False
        if member.role == Member.VIEWER and request.method not in SAFE_METHODS:
            return False
        if member.role == Member.OPERATOR and request.method == 'DELETE':
            return False
        set_scope(Scope(company_id=member.company_id,actor_id=request.user.pk))
        return True
