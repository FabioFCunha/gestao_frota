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

        with transaction.atomic():
            vehicle = (
                Vehicle.objects
                .select_for_update()
                .filter(horus_fleet_id=horus_fleet_id)
                .first()
            )

            # A placa serve apenas para reconciliar uma viatura legada sem
            # UUID Hórus; o vínculo permanente continua sendo horus_fleet_id.
            if vehicle is None and plate:
                plate_match = (
                    VehiclePlate.objects.select_for_update()
                    .filter(
                        plate__iexact=plate,
                        kind=VehiclePlate.CURRENT,
                        ends_on__isnull=True,
                    )
                    .select_related("vehicle")
                    .first()
                )
                if plate_match is not None:
                    matched_vehicle = plate_match.vehicle
                    if (
                        matched_vehicle.horus_fleet_id is not None
                        and matched_vehicle.horus_fleet_id != horus_fleet_id
                    ):
                        return Response(
                            {
                                "result": "error",
                                "detail": "A placa já está vinculada a outro ID Hórus.",
                                "plate": plate,
                                "vehicle_id": str(matched_vehicle.id),
                                "conflicting_horus_fleet_id": str(matched_vehicle.horus_fleet_id),
                            },
                            status=status.HTTP_409_CONFLICT,
                        )
                    vehicle = matched_vehicle

            if vehicle is None:
                vehicle_status = VehicleStatus.objects.filter(name="Ativo", active=True).first()
                if vehicle_status is None:
                    return Response({"result": "error", "detail": "Status 'Ativo' não encontrado no sistema."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
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
                # Preserve local status, colour and notes unless the source
                # explicitly sent that field.  Hórus does not own custody.
                update_fields = ["updated_at"]
                if vehicle.horus_fleet_id != horus_fleet_id:
                    vehicle.horus_fleet_id = horus_fleet_id
                    update_fields.append("horus_fleet_id")

                if "color" in data:
                    vehicle.color = data["color"]
                    update_fields.append("color")

                if "management_name" in data:
                    vehicle.notes = (
                        "Sincronizado do Horus. "
                        f"Gestao: {data['management_name']}"
                    )
                    update_fields.append("notes")

                vehicle.save(update_fields=update_fields)
                result = "updated"

            if plate:
                current_plate = (
                    vehicle.plate_history.select_for_update()
                    .filter(
                        kind=VehiclePlate.CURRENT,
                        ends_on__isnull=True,
                    )
                    .first()
                )

                if current_plate is None:
                    conflicting_plate = (
                        VehiclePlate.objects.select_for_update()
                        .filter(
                            plate__iexact=plate,
                            kind=VehiclePlate.CURRENT,
                            ends_on__isnull=True,
                        )
                        .exclude(vehicle_id=vehicle.id)
                        .first()
                    )
                    if conflicting_plate is not None:
                        return Response(
                            {
                                "result": "error",
                                "detail": "A placa já está em uso por outra viatura.",
                                "plate": plate,
                                "vehicle_id": str(vehicle.id),
                                "conflicting_vehicle_id": str(conflicting_plate.vehicle_id),
                            },
                            status=status.HTTP_409_CONFLICT,
                        )
                    VehiclePlate.objects.create(
                        vehicle=vehicle,
                        plate=plate,
                        kind=VehiclePlate.CURRENT,
                        starts_on=timezone.now(),
                        changed_by=None,
                    )

                elif current_plate.plate.upper() != plate:
                    conflicting_plate = (
                        VehiclePlate.objects.select_for_update()
                        .filter(
                            plate__iexact=plate,
                            kind=VehiclePlate.CURRENT,
                            ends_on__isnull=True,
                        )
                        .exclude(vehicle_id=vehicle.id)
                        .first()
                    )
                    if conflicting_plate is not None:
                        return Response(
                            {
                                "result": "error",
                                "detail": "A placa já está em uso por outra viatura.",
                                "plate": plate,
                                "vehicle_id": str(vehicle.id),
                                "conflicting_vehicle_id": str(conflicting_plate.vehicle_id),
                            },
                            status=status.HTTP_409_CONFLICT,
                        )
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
