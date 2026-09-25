from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import models
from django.utils import timezone
from .models import Maintenance, Vehicle, VehicleCustody, VehicleDriverAssignment
from .serializers import (
    DocumentSerializer, MaintenanceSerializer, SEIProcessSerializer,
    VehicleCustodySerializer, VehicleFineSerializer, VehicleHistorySerializer,
    VehicleInspectionSerializer, VehicleSerializer,
)

class DashboardAPIView(APIView):
    def get(self, request):
        if not request.user.has_perm("fleet.view_vehicle"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Permissão negada.")
            
        filters = {
            "unit": request.query_params.get("unit"),
            "base": request.query_params.get("base"),
            "renter": request.query_params.get("rental_company"),
            "status": request.query_params.get("vehicle_status"),
        }
        
        # Remove empty filters
        filters = {k: v for k, v in filters.items() if v}
        
        from .services import get_dashboard_metrics, get_operational_alerts
        
        metrics = get_dashboard_metrics(filters)
        alerts = get_operational_alerts(filters)
        
        return Response({
            "metrics": metrics,
            "alerts": alerts
        })


class VehicleViewSet(viewsets.ModelViewSet):
    queryset = Vehicle.objects.select_related(
        "brand", "model", "status", "contract", "renter", "unit", "base"
    ).prefetch_related(
        models.Prefetch("driver_assignments", queryset=VehicleDriverAssignment.objects.filter(is_active=True)),
        "plate_history",
        "mileage_history",
        "inspections"
    ).all()
    serializer_class = VehicleSerializer
    search_fields = ["plate_history__plate", "renavam", "contract__number"]
    filterset_fields = {"status": ["exact"], "armored": ["exact"], "renter": ["exact"], "unit": ["exact"], "base": ["exact"], "driver_assignments__driver": ["exact"]}

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        return Response(VehicleHistorySerializer(self.get_object().history.order_by("-created_at"), many=True).data)

    @action(detail=True, methods=["get"])
    def mileage_history(self, request, pk=None):
        vehicle = self.get_object()
        data = vehicle.mileage_history.values("id", "mileage", "date", "origin", "recorded_by__username", "notes", "is_correction")
        return Response(list(data))

    @action(detail=True, methods=["get"])
    def dossier(self, request, pk=None):
        from .serializers import (
            VehicleHistorySerializer, MaintenanceSerializer, VehicleInspectionSerializer,
            VehicleFineSerializer, SEIProcessSerializer, DocumentSerializer
        )
        
        # We fetch the vehicle and do prefetch on everything to avoid N+1
        vehicle = Vehicle.objects.prefetch_related(
            'plate_history',
            'mileage_history',
            'history',
            'inspections__type',
            'inspections__status',
            'maintenances__status',
            'maintenances__type',
            'fines__status',
            'sei_processes__status',
            'documents__document__status',
            'documents__document__versions'
        ).select_related(
            'status', 'unit', 'base', 'renter', 'contract'
        ).get(pk=self.get_object().id)
        
        data = {
            "vehicle": VehicleSerializer(vehicle).data,
            "plate_history": [
                {
                    "plate": p.plate,
                    "kind": p.kind,
                    "start_date": p.starts_on,
                    "end_date": p.ends_on,
                    "is_current": p.kind == VehiclePlate.CURRENT and p.ends_on is None,
                    "is_reserved": p.kind == VehiclePlate.RESERVED and p.ends_on is None,
                }
                for p in vehicle.plate_history.all()
            ],
            "mileage": [
                {"mileage": m.mileage, "date": m.date, "origin": m.origin, "is_correction": m.is_correction}
                for m in vehicle.mileage_history.order_by('-date')
            ],
            "inspections": VehicleInspectionSerializer(vehicle.inspections.all(), many=True).data,
            "maintenances": MaintenanceSerializer(vehicle.maintenances.all(), many=True).data,
            "fines": VehicleFineSerializer(vehicle.fines.all(), many=True).data,
            "history": VehicleHistorySerializer(vehicle.history.order_by('-created_at'), many=True).data,
            "sei_processes": SEIProcessSerializer([r.process for r in vehicle.sei_processes.all()], many=True).data,
            "documents": DocumentSerializer([r.document for r in vehicle.documents.all()], many=True).data
        }
        return Response(data)

    @action(detail=True, methods=["post"])
    def record_mileage(self, request, pk=None):
        from .services import record_vehicle_mileage
        vehicle = self.get_object()
        mileage = request.data.get("mileage")
        notes = request.data.get("notes", "")
        is_correction = request.data.get("is_correction", False)
        
        if not request.user.has_perm("fleet.add_vehiclemileage"):
            return Response({"error": "Permissão negada."}, status=403)
            
        try:
            record_vehicle_mileage(
                vehicle=vehicle,
                mileage=int(mileage) if mileage is not None else None,
                user=request.user,
                notes=notes,
                is_correction=is_correction
            )
            return Response({"status": "Quilometragem registrada com sucesso."})
        except ValueError as e:
            return Response({"error": str(e)}, status=400)


class MaintenanceViewSet(viewsets.ModelViewSet):
    queryset = Maintenance.objects.select_related("vehicle", "status", "type", "workshop").all()
    serializer_class = MaintenanceSerializer
    filterset_fields = ["vehicle", "status", "type", "workshop"]

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        from .services import complete_maintenance
        maintenance = self.get_object()
        resulting_status = request.data.get("resulting_status")
        reason = request.data.get("reason", "Manutenção concluída")
        try:
            complete_maintenance(maintenance=maintenance, user=request.user, resulting_status=resulting_status, reason=reason)
            return Response({"status": "Manutenção concluída com sucesso."})
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        from .services import cancel_maintenance
        maintenance = self.get_object()
        resulting_status = request.data.get("resulting_status")
        reason = request.data.get("reason", "Manutenção cancelada")
        try:
            cancel_maintenance(maintenance=maintenance, user=request.user, resulting_status=resulting_status, reason=reason)
            return Response({"status": "Manutenção cancelada com sucesso."})
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
            
from .models import VehicleInspection
from .serializers import VehicleInspectionSerializer

class VehicleInspectionViewSet(viewsets.ModelViewSet):
    queryset = VehicleInspection.objects.select_related("vehicle", "type", "status").all()
    serializer_class = VehicleInspectionSerializer
    filterset_fields = ["vehicle", "type", "status"]

    def perform_create(self, serializer):
        from .services import record_vehicle_inspection
        
        # intercept to use the service
        try:
            record_vehicle_inspection(
                vehicle=serializer.validated_data["vehicle"],
                type=serializer.validated_data["type"],
                status=serializer.validated_data["status"],
                user=self.request.user,
                inspector_name=serializer.validated_data.get("inspector_name", ""),
                mileage=serializer.validated_data.get("mileage"),
                notes=serializer.validated_data.get("notes", ""),
                date=serializer.validated_data.get("date")
            )
            # DRF requires setting an instance to serializer.instance for 201 response.
            # But the service creates the instance. Let's just fetch it.
            serializer.instance = VehicleInspection.objects.filter(vehicle=serializer.validated_data["vehicle"]).first()
        except ValueError as e:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(str(e))
            
    def perform_destroy(self, instance):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("Vistorias não podem ser excluídas fisicamente para preservar o histórico.")


from .models import VehicleFine
from .serializers import VehicleFineSerializer

class VehicleFineViewSet(viewsets.ModelViewSet):
    queryset = VehicleFine.objects.select_related("vehicle", "status").all()
    serializer_class = VehicleFineSerializer
    filterset_fields = {"vehicle": ["exact"], "status": ["exact"], "date": ["exact", "gte", "lte"], "auto_number": ["exact", "icontains"]}

    def perform_create(self, serializer):
        if not self.request.user.has_perm("fleet.add_vehiclefine"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Permissão negada.")
            
        from .services import create_vehicle_fine
        
        try:
            fine = create_vehicle_fine(
                vehicle=serializer.validated_data["vehicle"],
                auto_number=serializer.validated_data["auto_number"],
                agency=serializer.validated_data["agency"],
                status=serializer.validated_data["status"],
                date=serializer.validated_data["date"],
                user=self.request.user,
                process_number=serializer.validated_data.get("process_number", ""),
                amount=serializer.validated_data.get("amount"),
                due_date=serializer.validated_data.get("due_date"),
                notes=serializer.validated_data.get("notes", "")
            )
            serializer.instance = fine
        except ValueError as e:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(str(e))

    def perform_update(self, serializer):
        if not self.request.user.has_perm("fleet.change_vehiclefine"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Permissão negada.")
            
        from .services import update_vehicle_fine
        try:
            # We don't save the serializer directly. We use the service.
            fine = update_vehicle_fine(
                fine=self.get_object(),
                user=self.request.user,
                **serializer.validated_data
            )
            serializer.instance = fine
        except ValueError as e:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(str(e))

    def perform_destroy(self, instance):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("Multas não podem ser excluídas fisicamente para preservar o histórico e rastreabilidade.")

from .models import SEIProcess
from .serializers import SEIProcessSerializer

class SEIProcessViewSet(viewsets.ModelViewSet):
    queryset = SEIProcess.objects.select_related("status").all()
    serializer_class = SEIProcessSerializer
    filterset_fields = {"status": ["exact"], "sei_number": ["exact", "icontains"], "title": ["icontains"], "opening_date": ["exact", "gte", "lte"]}

    def perform_create(self, serializer):
        if not self.request.user.has_perm("fleet.add_seiprocess"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Permissão negada.")
            
        from .services import create_sei_process
        
        try:
            process = create_sei_process(
                sei_number=serializer.validated_data["sei_number"],
                status=serializer.validated_data["status"],
                user=self.request.user,
                title=serializer.validated_data.get("title", ""),
                category=serializer.validated_data.get("category", ""),
                opening_date=serializer.validated_data.get("opening_date"),
                notes=serializer.validated_data.get("notes", "")
            )
            serializer.instance = process
        except ValueError as e:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(str(e))

    def perform_update(self, serializer):
        if not self.request.user.has_perm("fleet.change_seiprocess"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Permissão negada.")
            
        from .services import update_sei_process
        try:
            process = update_sei_process(
                process=self.get_object(),
                user=self.request.user,
                **serializer.validated_data
            )
            serializer.instance = process
        except ValueError as e:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(str(e))

    def perform_destroy(self, instance):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("Processos SEI não podem ser excluídos fisicamente.")

from .models import Document
from .serializers import DocumentSerializer

class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.select_related("document_type", "status").prefetch_related("versions", "relations").all()
    serializer_class = DocumentSerializer
    filterset_fields = {"document_type": ["exact"], "status": ["exact"], "document_date": ["exact", "gte", "lte"]}

    def get_queryset(self):
        qs = super().get_queryset()
        status_name = self.request.query_params.get("status_name")
        if status_name:
            qs = qs.filter(status__name=status_name)
        else:
            if self.action == "list":
                qs = qs.exclude(status__name="Arquivado")
        return qs

    def perform_create(self, serializer):
        if not self.request.user.has_perm("fleet.add_document"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Permissão negada.")
            
        from .services import create_document
        
        file_obj = self.request.FILES.get('file')
        if not file_obj:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("O arquivo ('file') é obrigatório.")
            
        try:
            doc = create_document(
                title=serializer.validated_data.get("title", ""),
                document_type_id=self.request.data.get("document_type"),
                document_date=serializer.validated_data.get("document_date"),
                file_obj=file_obj,
                user=self.request.user,
                notes=serializer.validated_data.get("notes", "")
            )
            serializer.instance = doc
        except ValueError as e:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(str(e))

    def perform_update(self, serializer):
        if not self.request.user.has_perm("fleet.change_document"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Permissão negada.")
            
        from .services import add_document_version
        
        file_obj = self.request.FILES.get('file')
        doc = self.get_object()
        
        if file_obj:
            try:
                add_document_version(
                    document=doc,
                    file_obj=file_obj,
                    user=self.request.user,
                    notes=serializer.validated_data.get("notes", "")
                )
            except ValueError as e:
                from rest_framework.exceptions import ValidationError
                raise ValidationError(str(e))
                
        serializer.save(updated_at=timezone.now())

    def perform_destroy(self, instance):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("Documentos não podem ser excluídos fisicamente.")

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        if not request.user.has_perm("fleet.change_document"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Permissão negada.")
            
        from .services import archive_document
        doc = self.get_object()
        try:
            archive_document(document=doc, user=request.user, reason=request.data.get("reason", ""))
            return Response({"status": "Documento arquivado com sucesso."})
        except ValueError as e:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(str(e))

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        if not request.user.has_perm("fleet.view_document"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Permissão negada.")
            
        doc = self.get_object()
        version = doc.versions.first()
        if not version or not version.file:
            from rest_framework.exceptions import NotFound
            raise NotFound("Arquivo não encontrado.")
            
        from django.http import FileResponse
        response = FileResponse(version.file.open('rb'), content_type=version.mime_type)
        response['Content-Disposition'] = f'attachment; filename="{version.original_filename}"'
        return response


class VehicleCustodyViewSet(viewsets.ModelViewSet):
    queryset = VehicleCustody.objects.select_related("vehicle", "created_by").all()
    serializer_class = VehicleCustodySerializer
    filterset_fields = {
        "vehicle": ["exact"],
        "kind": ["exact"],
        "starts_on": ["exact", "gte", "lte"],
        "ends_on": ["exact", "isnull"],
    }

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_destroy(self, instance):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied(
            "Registros de acautelamento não podem ser excluídos fisicamente."
        )
