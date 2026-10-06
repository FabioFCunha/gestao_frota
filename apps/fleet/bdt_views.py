from django.db.models import Q
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from uuid import UUID

from .bdt_serializers import BDTSerializer
from .models import BDT


class BDTViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Consulta somente leitura dos BDTs sincronizados do Horus.
    """

    permission_classes = [IsAuthenticated]

    queryset = (
        BDT.objects
        .select_related("vehicle", "driver")
        .prefetch_related("vehicle__plate_history")
        .all()
    )

    serializer_class = BDTSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        activity = self.request.query_params.get("vehicle_active", "true").lower()
        if activity in {"false", "inactive", "0"}:
            qs = qs.filter(vehicle__active=False)
        elif activity not in {"all", ""}:
            qs = qs.filter(vehicle__active=True)

        vehicle = self.request.query_params.get("vehicle")
        driver = self.request.query_params.get("driver")
        management = self.request.query_params.get("management")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        search = self.request.query_params.get("search")
        status_filter = self.request.query_params.get("status")

        if vehicle:
            try:
                vehicle_id = UUID(str(vehicle))
            except (ValueError, TypeError, AttributeError):
                return qs.none()
            qs = qs.filter(vehicle_id=vehicle_id)

        if driver:
            qs = qs.filter(driver_id=driver)

        if management:
            qs = qs.filter(horus_management_id=management)

        if date_from:
            qs = qs.filter(started_at__date__gte=date_from)

        if date_to:
            qs = qs.filter(started_at__date__lte=date_to)

        if search:
            qs = qs.filter(
                Q(vehicle__plate_history__plate__icontains=search)
                | Q(driver__name__icontains=search)
                | Q(note__icontains=search)
                | Q(external_id__icontains=search)
            ).distinct()

        if status_filter == "ABERTO":
            qs = qs.filter(
                ended_km__isnull=True,
                horus_active=True,
            )

        elif status_filter == "DADOS_INCOMPLETOS":
            qs = qs.filter(
                Q(started_km__isnull=True)
                | Q(started_km="")
                | Q(ended_km__isnull=True, horus_active=False)
            )

        elif status_filter == "CALCULADA":
            qs = qs.filter(
                started_km__isnull=False,
                started_km__gt="",
                ended_km__isnull=False,
                ended_km__gt="",
            )

        return qs
