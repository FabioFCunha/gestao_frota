from rest_framework import serializers
from .models import Maintenance, Vehicle, VehicleHistory
from .services import open_maintenance


class VehicleSerializer(serializers.ModelSerializer):
    current_driver = serializers.SerializerMethodField()
    current_plate = serializers.SerializerMethodField()
    reserved_plate = serializers.SerializerMethodField()
    current_mileage = serializers.SerializerMethodField()
    latest_inspection_date = serializers.SerializerMethodField()
    latest_inspection_status = serializers.SerializerMethodField()

    class Meta:
        model = Vehicle
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at", "created_by", "current_mileage", "current_driver", "current_plate", "reserved_plate", "latest_inspection_date", "latest_inspection_status"]

    def get_current_driver(self, obj):
        active_assignment = next((a for a in obj.driver_assignments.all() if a.is_active), None)
        if active_assignment:
            return active_assignment.driver_id
        return None

    def get_current_plate(self, obj):
        active_plate = next((p for p in obj.plate_history.all() if p.kind == "CURRENT" and p.ends_on is None), None)
        return active_plate.plate if active_plate else ""

    def get_current_mileage(self, obj):
        latest = next(iter(obj.mileage_history.all()), None)
        return latest.mileage if latest else 0

    def get_reserved_plate(self, obj):
        active_plate = next((p for p in obj.plate_history.all() if p.kind == "RESERVED" and p.ends_on is None), None)
        return active_plate.plate if active_plate else ""


    def get_latest_inspection_date(self, obj):
        latest = next(iter(obj.inspections.all()), None)
        return latest.date if latest else None

    def get_latest_inspection_status(self, obj):
        latest = next(iter(obj.inspections.all()), None)
        return latest.status.name if latest and latest.status else None


class VehicleHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleHistory
        fields = "__all__"
        read_only_fields = ["id", "created_at", "changed_by"]

from .models import VehicleInspection

class VehicleInspectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleInspection
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

from .models import VehicleFine

class VehicleFineSerializer(serializers.ModelSerializer):
    sei_process = serializers.SerializerMethodField()

    class Meta:
        model = VehicleFine
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at", "created_by", "sei_process"]

    def get_sei_process(self, obj):
        relation = obj.sei_processes.first()
        if relation:
            return SEIProcessSerializer(relation.process).data
        return None


from .models import SEIProcess, SEIProcessRelation

class SEIProcessRelationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SEIProcessRelation
        fields = ["id", "content_type", "object_id", "created_at"]

class SEIProcessSerializer(serializers.ModelSerializer):
    class Meta:
        model = SEIProcess
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

from .models import Document, DocumentVersion, DocumentRelation

class DocumentRelationSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentRelation
        fields = ["id", "content_type", "object_id", "created_at"]

class DocumentVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentVersion
        fields = ["id", "original_filename", "file_extension", "mime_type", "file_size", "created_at", "updated_at", "uploaded_by"]

class DocumentSerializer(serializers.ModelSerializer):
    versions = DocumentVersionSerializer(many=True, read_only=True)
    relations = DocumentRelationSerializer(many=True, read_only=True)
    
    class Meta:
        model = Document
        fields = "__all__"
        read_only_fields = ["id", "status", "created_at", "updated_at", "created_by"]

class MaintenanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Maintenance
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at", "opened_by", "resolved_by", "vehicle_status_before_opening"]

    def create(self, validated_data):
        maintenance = super().create(validated_data)
        return open_maintenance(maintenance=maintenance, user=self.context["request"].user)
