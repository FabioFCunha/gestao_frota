from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BDT, Driver, Vehicle
from .sync_permissions import HasFleetSyncToken
from .sync_serializers import BDTSyncSerializer


class BDTSyncAPIView(APIView):
    """
    Endpoint receptor dos BDTs enviados pelo agente Windows.

    Arquitetura:
        Horus -> Windows -> HTTPS -> Gestao de Frotas
    """

    authentication_classes = []
    permission_classes = [HasFleetSyncToken]

    def post(self, request):
        # Allow passing a list of dicts (batch) or a single dict
        data = request.data if isinstance(request.data, list) else [request.data]
        
        serializer = BDTSyncSerializer(data=data, many=True)
        serializer.is_valid(raise_exception=True)

        from .sync_bdt import BDTSyncWorker
        worker = BDTSyncWorker(serializer.validated_data)
        
        # Centraliza o mapping de IDs de operacao
        resumo = worker.run(managements_map={49: "Lei Seca", 125: "SEGOV - ADM"})

        return Response(resumo, status=status.HTTP_200_OK)

