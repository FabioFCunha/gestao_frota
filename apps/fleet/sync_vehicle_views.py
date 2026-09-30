from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Driver, Vehicle, VehiclePlate, VehicleStatus
from .sync_permissions import HasFleetSyncToken
from .sync_serializers import VehicleSyncSerializer


class VehicleSyncAPIView(APIView):
    """
    Endpoint receptor dos veiculos enviados pelo agente Windows.

    O ID do fleet no Horus e armazenado em Vehicle.horus_fleet_id.
    """

    authentication_classes = []
    permission_classes = [HasFleetSyncToken]

    def post(self, request):
        serializer = VehicleSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        horus_fleet_id = data["external_id"]
        plate = data.get("plate", "").strip().upper()
        source_updated_at = data.get("source_updated_at")

        vehicle_status = VehicleStatus.objects.filter(
            name="Ativo",
            active=True,
        ).first()

        if vehicle_status is None:
            return Response(
                {
                    "result": "error",
                    "detail": (
                        "Situacao de veiculo 'Ativo' nao encontrada."
                    ),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        with transaction.atomic():
            vehicle = (
                Vehicle.objects
                .select_for_update()
                .filter(horus_fleet_id=horus_fleet_id)
                .first()
            )

            if vehicle is None:
                vehicle = Vehicle.objects.create(
                    horus_fleet_id=horus_fleet_id,
                    color=data.get("color", ""),
                    status=vehicle_status,
                    notes=(
                        "Sincronizado do Horus. "
                        f"Gestao: {data.get('management_name', '')}"
                    ).strip(),
                )

                result = "created"

            else:
                vehicle.color = data.get("color", "")
                vehicle.status = vehicle_status

                if data.get("management_name"):
                    vehicle.notes = (
                        "Sincronizado do Horus. "
                        f"Gestao: {data['management_name']}"
                    )

                vehicle.save(
                    update_fields=[
                        "color",
                        "status",
                        "notes",
                        "updated_at",
                    ]
                )

                result = "updated"

            if plate:
                current_plate = (
                    vehicle.plate_history
                    .filter(
                        kind=VehiclePlate.CURRENT,
                        ends_on__isnull=True,
                    )
                    .first()
                )

                if current_plate is None:
                    VehiclePlate.objects.create(
                        vehicle=vehicle,
                        plate=plate,
                        kind=VehiclePlate.CURRENT,
                        starts_on=timezone.now(),
                        changed_by=None,
                    )

                elif current_plate.plate != plate:
                    current_plate.ends_on = timezone.now()
                    current_plate.save(update_fields=["ends_on"])

                    VehiclePlate.objects.create(
                        vehicle=vehicle,
                        plate=plate,
                        kind=VehiclePlate.CURRENT,
                        starts_on=timezone.now(),
                        changed_by=None,
                    )

        return Response(
            {
                "result": result,
                "external_id": str(horus_fleet_id),
                "vehicle_id": str(vehicle.id),
            },
            status=(
                status.HTTP_201_CREATED
                if result == "created"
                else status.HTTP_200_OK
            ),
        )
