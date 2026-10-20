from rest_framework.permissions import IsAuthenticated
from apps.fleet.tenant_scope import Scope, set_scope
from .models import Member


class CompanyAuthenticated(IsAuthenticated):
    def has_permission(self,request,view):
        if not super().has_permission(request,view):
            return False
        if request.user.is_superuser:
            set_scope(None)
            return True
        member=Member.objects.filter(user=request.user,active=True,company__active=True,role='manager').first()
        if not member:
            return False
        set_scope(Scope(company_id=member.company_id,actor_id=request.user.pk))
        return True
