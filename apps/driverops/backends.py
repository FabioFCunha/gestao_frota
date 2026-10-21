from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import Permission
from apps.fleet.tenant_scope import company_id
from .models import Member


class CompanyManagerBackend(BaseBackend):
    """Fleet permissions only inside the authenticated company's request scope."""
    def get_all_permissions(self,user_obj,obj=None):
        if obj is not None or not user_obj.is_active or not company_id():
            return set()
        member = Member.objects.filter(user=user_obj, active=True,
            company_id=company_id(), company__active=True).first()
        if not member or member.role not in Member.DESKTOP_ROLES:
            return set()
        names = Permission.objects.filter(content_type__app_label='fleet').values_list('codename', flat=True)
        if member.role == Member.VIEWER:
            names = [name for name in names if name.startswith('view_')]
        elif member.role == Member.OPERATOR:
            names = [name for name in names if name.startswith(('view_', 'add_', 'change_')) or name == 'manage_vehicle_status']
        return {'fleet.' + name for name in names}

    def has_perm(self,user_obj,perm,obj=None):
        return perm in self.get_all_permissions(user_obj,obj)
