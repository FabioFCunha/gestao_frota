from rest_framework import serializers

from .models import BDT


class BDTSerializer(serializers.ModelSerializer):
    vehicle_plate = serializers.SerializerMethodField()
    driver_name = serializers.SerializerMethodField()
    km_status_display = serializers.SerializerMethodField()
    total_km = serializers.ReadOnlyField()

    class Meta:
        model = BDT
        fields = [
            "id",
            "external_id",
            "vehicle",
            "vehicle_plate",
            "driver",
            "driver_name",
            "horus_management_id",
            "management_name",
            "horus_adm_id",
            "horus_service_id",
            "horus_sector_id",
            "started_at",
            "ended_at",
            "started_km",
            "ended_km",
            "total_km",
            "km_status",
            "km_status_display",
            "latitude_match",
            "longitude_match",
            "latitude_retreat",
            "longitude_retreat",
            "note",
            "horus_active",
            "source_created_at",
            "source_updated_at",
            "last_synced_at",
            "created_at",
            "updated_at",
        ]

    def get_vehicle_plate(self, obj):
        if not obj.vehicle:
            return ""

        plate = (
            obj.vehicle.plate_history
            .filter(kind="CURRENT", ends_on__isnull=True)
            .values_list("plate", flat=True)
            .first()
        )

        return plate or ""

    def get_driver_name(self, obj):
        return obj.driver.name if obj.driver else ""

    def get_km_status_display(self, obj):
        labels = {
            "CALCULADA": "Calculada",
            "DADOS_INCOMPLETOS": "Dados incompletos",
            "FORMATO_INVALIDO": "Formato inválido",
            "QUILOMETRAGEM_NEGATIVA": "Quilometragem negativa",
        }

        return labels.get(obj.km_status, obj.km_status)
