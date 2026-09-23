import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType


class SystemParameter(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    def __str__(self):
        return self.key

class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True


class NamedModel(BaseModel):
    name = models.CharField(max_length=150)
    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self):
        return self.name


class VehicleStatus(NamedModel):
    color = models.CharField(max_length=7, default="#64748B")
    class Meta(NamedModel.Meta):
        verbose_name_plural = "situações de veículo"


class Renter(NamedModel):
    cnpj = models.CharField(max_length=18, blank=True, null=True, unique=True)
    contact = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)


class AdministrativeUnit(NamedModel):
    acronym = models.CharField(max_length=20, unique=True)
    responsible = models.CharField(max_length=150, blank=True)
    contact = models.CharField(max_length=150, blank=True)


class Base(NamedModel):
    unit = models.ForeignKey(AdministrativeUnit, on_delete=models.PROTECT, related_name="bases")
    address = models.TextField(blank=True)
    responsible = models.CharField(max_length=150, blank=True)
    contact = models.CharField(max_length=150, blank=True)
    class Meta(NamedModel.Meta):
        constraints = [models.UniqueConstraint(fields=["unit", "name"], name="unique_base_per_unit")]


class Brand(NamedModel):
    name = models.CharField(max_length=100, unique=True)


class VehicleModel(NamedModel):
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="models")
    class Meta(NamedModel.Meta):
        constraints = [models.UniqueConstraint(fields=["brand", "name"], name="unique_model_per_brand")]


class Driver(NamedModel):
    registration = models.CharField(max_length=50, blank=True, null=True, unique=True)
    unit = models.ForeignKey(AdministrativeUnit, null=True, blank=True, on_delete=models.PROTECT)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    cnh_number = models.CharField("Nº CNH", max_length=20, blank=True)
    cnh_category = models.CharField("Categoria", max_length=5, blank=True)
    cnh_expiration = models.DateField("Validade CNH", null=True, blank=True)
    sei_acautelamento = models.CharField(
        "SEI do acautelamento",
        max_length=100,
        blank=True,
    )


class Contract(BaseModel):
    number = models.CharField(max_length=80, unique=True)
    renter = models.ForeignKey(Renter, on_delete=models.PROTECT, related_name="contracts")
    starts_on = models.DateField()
    ends_on = models.DateField(db_index=True)
    administrative_status = models.CharField(max_length=30, default="VIGENTE")
    notes = models.TextField(blank=True)
    sei_processes = GenericRelation('SEIProcessRelation')
    documents = GenericRelation('DocumentRelation')

    def __str__(self):
        return f"{self.number} ({self.renter.name})"

    def clean(self):
        if self.ends_on < self.starts_on: raise ValidationError("O término não pode anteceder o início.")


class Vehicle(BaseModel):
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.PROTECT)
    model = models.ForeignKey(VehicleModel, null=True, blank=True, on_delete=models.PROTECT)
    color = models.CharField(max_length=50, blank=True)
    renavam = models.CharField(max_length=20, blank=True, null=True, unique=True)
    contract = models.ForeignKey(Contract, null=True, blank=True, on_delete=models.PROTECT, related_name="vehicles")
    renter = models.ForeignKey(Renter, null=True, blank=True, on_delete=models.PROTECT)
    unit = models.ForeignKey(AdministrativeUnit, null=True, blank=True, on_delete=models.PROTECT)
    base = models.ForeignKey(Base, null=True, blank=True, on_delete=models.PROTECT)
    status = models.ForeignKey(VehicleStatus, on_delete=models.PROTECT)
    armored = models.BooleanField(default=False)
    custody_info = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="vehicles_created")
    sei_processes = GenericRelation('SEIProcessRelation')
    documents = GenericRelation('DocumentRelation')
    class Meta:
        indexes = [models.Index(fields=["status"]), models.Index(fields=["unit", "base"])]


class VehicleDriverAssignment(BaseModel):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="driver_assignments")
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT, related_name="vehicle_assignments")
    starts_on = models.DateTimeField(default=timezone.now)
    ends_on = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle"], 
                condition=Q(is_active=True), 
                name="unique_active_driver_per_vehicle"
            )
        ]


class VehiclePlate(BaseModel):
    CURRENT, RESERVED = "CURRENT", "RESERVED"
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="plate_history")
    plate = models.CharField(max_length=8, db_index=True)
    kind = models.CharField(max_length=10, choices=[(CURRENT, "Atual"), (RESERVED, "Reservada")])
    starts_on = models.DateTimeField(default=timezone.now)
    ends_on = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plate"], condition=Q(ends_on__isnull=True, kind="CURRENT"), name="unique_active_current_plate"),
            models.UniqueConstraint(fields=["vehicle", "kind"], condition=Q(ends_on__isnull=True), name="unique_active_plate_per_vehicle_and_kind")
        ]


class VehicleMileage(BaseModel):
    MANUAL = "MANUAL"
    INTEGRACAO = "INTEGRACAO"
    ORIGIN_CHOICES = [
        (MANUAL, "Manual"),
        (INTEGRACAO, "Integração"),
    ]

    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="mileage_history")
    mileage = models.PositiveIntegerField()
    date = models.DateTimeField(default=timezone.now)
    origin = models.CharField(max_length=20, choices=ORIGIN_CHOICES, default=MANUAL)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    is_correction = models.BooleanField(default=False)
    external_id = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-date", "-created_at"]


class VehicleInspectionType(NamedModel): pass
class VehicleInspectionStatus(NamedModel): pass

class VehicleInspection(BaseModel):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="inspections")
    date = models.DateTimeField(default=timezone.now)
    type = models.ForeignKey(VehicleInspectionType, on_delete=models.PROTECT)
    status = models.ForeignKey(VehicleInspectionStatus, on_delete=models.PROTECT)
    inspector_name = models.CharField(max_length=150, blank=True)
    mileage = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    sei_processes = GenericRelation('SEIProcessRelation')
    documents = GenericRelation('DocumentRelation')

    class Meta:
        ordering = ["-date", "-created_at"]


class VehicleFineStatus(NamedModel): pass

class VehicleFine(BaseModel):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="fines")
    auto_number = models.CharField(max_length=50, db_index=True)
    agency = models.CharField(max_length=150)
    status = models.ForeignKey(VehicleFineStatus, on_delete=models.PROTECT)
    date = models.DateTimeField()
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    sei_processes = GenericRelation('SEIProcessRelation')
    documents = GenericRelation('DocumentRelation')

    class Meta:
        ordering = ["-date", "-created_at"]


class MaintenanceStatus(NamedModel): pass
class MaintenanceType(NamedModel): pass


class Workshop(NamedModel):
    cnpj = models.CharField(max_length=18, blank=True, null=True, unique=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)


from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation

class SEIProcessStatus(NamedModel): pass

class SEIProcess(BaseModel):
    sei_number = models.CharField(max_length=80, unique=True)
    title = models.CharField(max_length=200, blank=True)
    status = models.ForeignKey(SEIProcessStatus, on_delete=models.PROTECT)
    category = models.CharField(max_length=100, blank=True)
    opening_date = models.DateField(null=True, blank=True)
    closing_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    documents = GenericRelation('DocumentRelation')

    class Meta:
        ordering = ["-created_at"]

class SEIProcessRelation(BaseModel):
    process = models.ForeignKey(SEIProcess, on_delete=models.CASCADE, related_name="relations")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField(db_index=True)
    content_object = GenericForeignKey("content_type", "object_id")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)

    class Meta:
        unique_together = ("process", "content_type", "object_id")

class DocumentType(NamedModel): pass
class DocumentStatus(NamedModel): pass

class Document(BaseModel):
    title = models.CharField(max_length=255)
    document_type = models.ForeignKey(DocumentType, on_delete=models.PROTECT)
    status = models.ForeignKey(DocumentStatus, on_delete=models.PROTECT)
    document_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-created_at"]

def document_upload_path(instance, filename):
    import uuid
    import os
    ext = filename.split('.')[-1]
    name = f"{uuid.uuid4().hex}.{ext}"
    return os.path.join('documents', str(instance.document.id), name)

class DocumentVersion(BaseModel):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    file = models.FileField(upload_to=document_upload_path)
    original_filename = models.CharField(max_length=255)
    file_extension = models.CharField(max_length=10)
    mime_type = models.CharField(max_length=100)
    file_size = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-created_at"]

class DocumentRelation(BaseModel):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="relations")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField(db_index=True)
    content_object = GenericForeignKey("content_type", "object_id")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        unique_together = ("document", "content_type", "object_id")


class Maintenance(BaseModel):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="maintenances")
    workshop = models.ForeignKey(Workshop, null=True, blank=True, on_delete=models.PROTECT)
    type = models.ForeignKey(MaintenanceType, on_delete=models.PROTECT)
    status = models.ForeignKey(MaintenanceStatus, on_delete=models.PROTECT)
    mileage = models.PositiveIntegerField(null=True, blank=True)
    service = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    entered_at = models.DateTimeField(default=timezone.now)
    exited_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    vehicle_status_before_opening = models.ForeignKey(VehicleStatus, null=True, blank=True, on_delete=models.PROTECT, related_name="maintenance_previous_statuses")
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="maintenances_opened")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="maintenances_resolved")
    sei_processes = GenericRelation('SEIProcessRelation')
    documents = GenericRelation('DocumentRelation')

class VehicleHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="history")
    field = models.CharField(max_length=100)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    module = models.CharField(max_length=80)
    action = models.CharField(max_length=40)
    entity_type = models.CharField(max_length=80)
    entity_id = models.UUIDField()
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
