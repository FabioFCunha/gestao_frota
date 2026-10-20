import hashlib
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import DeviceSession


class DeviceAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header:
            return None
        if not header.startswith("Bearer "):
            raise AuthenticationFailed("Autenticação inválida.")
        token = header[7:]
        session = DeviceSession.objects.select_related("member__user", "member__company").filter(
            key_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at__gt=timezone.now(),
        ).first()
        if not session or not session.member.active or not session.member.company.active:
            raise AuthenticationFailed("Sessão expirada ou acesso desativado.")
        from apps.fleet.tenant_scope import Scope, set_scope
        set_scope(Scope(company_id=session.member.company_id,actor_id=session.member.user_id))
        user = session.member.user
        if not user.is_active or user.must_change_password or user.last_changed_at > session.created_at:
            raise AuthenticationFailed("Atualize sua senha pelo portal.")
        return user, session

    def authenticate_header(self, request):
        return "Bearer"
