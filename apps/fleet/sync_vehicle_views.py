from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Vehicle, VehiclePlate, VehicleStatus
from .sync_permissions import HasFleetSyncToken
from .sync_serializers import VehicleSyncSerializer


class VehicleSyncAPIView(APIView):
    """
    Endpoint receptor dos veiculos enviados pelo agente Windows.

    O ID do fleet no Horus e armazenado em Vehicle.horus_fleet_id.

    Estrategia de reconciliacao inteligente:

    1. Procurar primeiro por: Vehicle.horus_fleet_id = external_id
    2. Se nao encontrar e houver placa: procurar uma VehiclePlate atual (mesma placa case-insensitive, kind=CURRENT, ends_on IS NULL).
    3. Se encontrar uma Vehicle existente pela placa:
       - NÃO criar outra Vehicle.
       - se vehicle.horus_fleet_id estiver NULL, preencher com o external_id.
       - atualizar apenas os campos sincronizados (color, status, notes).
    4. Se encontrar a placa em uma Vehicle que ja possui outro horus_fleet_id diferente:
       - retornar HTTP 409 (conflito).
    5. Somente se nao existir nem por ID nem por placa atual, entao criar uma nova Vehicle.
    6. Ao criar/trocar placa, nunca criar duplicata e retornar 409 se a placa ja estiver vinculada a outra viatura.
    """

    authentication_classes = []
    permission_classes = [HasFleetSyncToken]

    def post(self, request):
        serializer = VehicleSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        horus_fleet_id = data["external_id"]
        plate = (data.get("plate") or "").strip().upper()

        with transaction.atomic():
            # ==========================================================
            # 1. TENTA BUSCAR POR HORUS_FLEET_ID
            # ==========================================================
            vehicle = (
                Vehicle.objects
                .select_for_update()
                .filter(horus_fleet_id=horus_fleet_id)
                .first()
            )
            result = None

            # ==========================================================
            # 2. SE NAO ENCONTRAR, TENTA BUSCAR PELA PLACA ATUAL
            # ==========================================================
            if vehicle is None and plate:
                plate_match = (
                    VehiclePlate.objects
                    .select_for_update()
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
                    # 4. Verifica conflito de horus_fleet_id
                    if matched_vehicle.horus_fleet_id is not None and matched_vehicle.horus_fleet_id != horus_fleet_id:
                        return Response(
                            {
                                "result": "error",
                                "detail": (
                                    f"A placa {plate} ja esta vinculada a uma viatura "
                                    f"com outro horus_fleet_id ({matched_vehicle.horus_fleet_id})."
                                ),
                                "plate": plate,
                                "vehicle_id": str(matched_vehicle.id),
                                "conflicting_horus_fleet_id": str(matched_vehicle.horus_fleet_id),
                            },
                            status=status.HTTP_409_CONFLICT,
                        )
                    # 3. Utiliza a viatura existente
                    vehicle = matched_vehicle
            
            # ==========================================================
            # 5. CRIAR VIATURA SOMENTE SE NAO EXISTIR POR ID NEM PLACA
            # ==========================================================
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

            # ==========================================================
            # 6. SINCRONIZAR A PLACA
            # ==========================================================
            if plate:
                current_plate = (
                    vehicle.plate_history
                    .select_for_update()
                    .filter(
                        kind=VehiclePlate.CURRENT,
                        ends_on__isnull=True,
                    )
                    .first()
                )

                if current_plate is None:
                    # Nao tem placa. Verifica se a placa ja pertence a outra viatura.
                    conflicting_plate = (
                        VehiclePlate.objects
                        .select_for_update()
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
                                "detail": f"A placa {plate} ja esta em uso por outra viatura.",
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
                    # Tem placa, mas eh diferente. Verifica se a nova placa pertence a outra viatura.
                    conflicting_plate = (
                        VehiclePlate.objects
                        .select_for_update()
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
                                "detail": f"A placa {plate} ja esta em uso por outra viatura.",
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
