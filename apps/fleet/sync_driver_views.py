from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Driver
from .sync_permissions import HasFleetSyncToken
from .sync_serializers import DriverSyncSerializer

class DriverSyncAPIView(APIView):
    """
    Endpoint receptor dos motoristas enviados pelo agente Windows.
    O ID do user no Horus é armazenado em Driver.horus_user_id.
    """

    authentication_classes = []
    permission_classes = [HasFleetSyncToken]

    def post(self, request):
        data = request.data if isinstance(request.data, list) else [request.data]
        serializer = DriverSyncSerializer(data=data, many=True)
        serializer.is_valid(raise_exception=True)

        resumo = {"processados": len(serializer.validated_data), "criados": 0, "atualizados": 0, "inalterados": 0}

        with transaction.atomic():
            for item in serializer.validated_data:
                horus_user_id = item["external_id"]
                name = item.get("name", "").strip() or f'Horus {horus_user_id}'
                registration = item.get("registration", "")

                driver, created = Driver.objects.get_or_create(
                    horus_user_id=horus_user_id,
                    defaults={"name": name, "registration": registration}
                )

                changed = False
                if not created:
                    if name and driver.name != name:
                        driver.name = name
                        changed = True
                    if registration and not driver.registration:
                        driver.registration = registration
                        changed = True

                    if changed:
                        driver.save(update_fields=["name", "registration", "updated_at"])
                        resumo["atualizados"] += 1
                    else:
                        resumo["inalterados"] += 1
                else:
                    resumo["criados"] += 1

        return Response(resumo, status=status.HTTP_200_OK)
