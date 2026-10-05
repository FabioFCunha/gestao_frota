from django.conf import settings
from rest_framework.permissions import BasePermission


class HasFleetSyncToken(BasePermission):
    """
    Permite acesso somente ao agente Windows de sincronizacao
    que conhece o token compartilhado.
    """

    message = "Token de sincronizacao invalido."

    def has_permission(self, request, view):
        configured_token = str(
            getattr(settings, "FLEET_SYNC_TOKEN", "") or ""
        ).strip()

        if not configured_token:
            return False

        authorization = request.headers.get("Authorization", "").strip()

        if not authorization.startswith("Bearer "):
            return False

        supplied_token = authorization[7:].strip()

        return supplied_token == configured_token
