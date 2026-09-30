from rest_framework import serializers

from .models import BDT


class BDTSyncSerializer(serializers.Serializer):
    """
    Payload recebido pelo agente Windows que consulta o Horus.
    """

    id = serializers.UUIDField(required=True)
    fleet_id = serializers.UUIDField(required=False, allow_null=True)
    user_id = serializers.UUIDField(required=False, allow_null=True)
    management_id = serializers.IntegerField(required=False, allow_null=True)
    adm_id = serializers.UUIDField(required=False, allow_null=True)
    service_id = serializers.UUIDField(required=False, allow_null=True)
    sector_id = serializers.IntegerField(required=False, allow_null=True)
    
    started_at = serializers.DateTimeField(required=False, allow_null=True)
    ended_at = serializers.DateTimeField(required=False, allow_null=True)
    
    started_km = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    ended_km = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    
    latitude_match = serializers.DecimalField(max_digits=12, decimal_places=8, required=False, allow_null=True)
    longitude_match = serializers.DecimalField(max_digits=12, decimal_places=8, required=False, allow_null=True)
    latitude_retreat = serializers.DecimalField(max_digits=12, decimal_places=8, required=False, allow_null=True)
    longitude_retreat = serializers.DecimalField(max_digits=12, decimal_places=8, required=False, allow_null=True)
    
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    active = serializers.BooleanField(required=False, allow_null=True)
    
    created_at = serializers.DateTimeField(required=False, allow_null=True)
    updated_at = serializers.DateTimeField(required=False, allow_null=True)



class VehicleSyncSerializer(serializers.Serializer):
    """
    Payload recebido do agente Windows para sincronizacao de veiculos
    originados no Horus.
    """

    external_id = serializers.UUIDField()
    plate = serializers.CharField(
        max_length=8,
        required=False,
        allow_blank=True,
    )
    special_plate = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
    )
    color = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
    )
    type_vehicle = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    driver_horus_user_id = serializers.UUIDField(
        required=False,
        allow_null=True,
    )
    management_id = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    management_name = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
    )
    source_updated_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
    )
