import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from apps.fleet.utils import normalize_km


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


class Sector(NamedModel):
    slug = models.SlugField(unique=True, max_length=50)


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
    sectors = models.ManyToManyField(
        "Sector", related_name="drivers", blank=True, verbose_name="Setores",
    )
    horus_user_id = models.UUIDField(
        null=True, blank=True, unique=True,
        help_text="ID do usuario na tabela users do Horus.",
    )
    registration = models.CharField(max_length=50, blank=True, null=True, unique=True)
    unit = models.ForeignKey(AdministrativeUnit, null=True, blank=True, on_delete=models.PROTECT)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    cnh_number = models.CharField("Nº CNH", max_length=20, blank=True)
    cnh_category = models.CharField("Categoria", max_length=5, blank=True)
    cnh_expiration = models.DateField("Validade CNH", null=True, blank=True)


class DriverCNHHistory(BaseModel):
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="cnh_history")
    renewal_date = models.DateField("Data da renovação")
    new_expiration = models.DateField("Nova validade")
    cnh_number = models.CharField("Nº CNH", max_length=20, blank=True)
    cnh_category = models.CharField("Categoria", max_length=5, blank=True)

    class Meta:
        ordering = ['-renewal_date', '-created_at']


class Contract(BaseModel):
    number = models.CharField(max_length=80, unique=True)
    renter = models.ForeignKey(Renter, on_delete=models.PROTECT, related_name="contracts")
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True, db_index=True)
    administrative_status = models.CharField(max_length=30, default="VIGENTE")
    notes = models.TextField(blank=True)
    sei_processes = GenericRelation('SEIProcessRelation')
    documents = GenericRelation('DocumentRelation')

    def __str__(self):
        return f"{self.number} ({self.renter.name})"

    def clean(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError("O término não pode anteceder o início.")


class Vehicle(BaseModel):
    horus_fleet_id = models.UUIDField(
        null=True, blank=True, unique=True,
        help_text="ID do veiculo na tabela fleets do Horus.",
    )
    # Snapshot explicitamente inicializado fora das views.  Impede que a meta
    # de primeira revisão se mova a cada nova leitura de quilometragem.
    revision_reference_km = models.PositiveIntegerField(null=True, blank=True)
    revision_reference_at = models.DateTimeField(null=True, blank=True)
    revision_reference_source = models.CharField(max_length=100, blank=True)
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.PROTECT)
    model = models.ForeignKey(VehicleModel, null=True, blank=True, on_delete=models.PROTECT)
    color = models.CharField(max_length=50, blank=True)
    renavam = models.CharField(max_length=20, blank=True, null=True, unique=True)
    chassi = models.CharField(max_length=17, blank=True, null=True, unique=True)
    crlv_exercise = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Exercício do CRLV")
    contract = models.ForeignKey(Contract, null=True, blank=True, on_delete=models.PROTECT, related_name="vehicles")
    renter = models.ForeignKey(Renter, null=True, blank=True, on_delete=models.PROTECT)
    unit = models.ForeignKey(AdministrativeUnit, null=True, blank=True, on_delete=models.PROTECT)
    base = models.ForeignKey(Base, null=True, blank=True, on_delete=models.PROTECT)
    sector = models.ForeignKey(Sector, null=True, blank=True, on_delete=models.PROTECT, related_name="vehicles")
    status = models.ForeignKey(VehicleStatus, on_delete=models.PROTECT)
    armored = models.BooleanField(default=False)
    custody_info = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="vehicles_created")
    sei_processes = GenericRelation('SEIProcessRelation')
    documents = GenericRelation('DocumentRelation')
    class Meta:
        indexes = [models.Index(fields=["status"]), models.Index(fields=["unit", "base"])]
        permissions = [
            ("manage_vehicle_status", "Pode gerenciar situação administrativa da viatura"),
        ]


class VehicleExitOrderNumberSequence(models.Model):
    """Serializador da numeração humana das ordens de saída."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    value = models.PositiveBigIntegerField(default=0)


class VehicleExitOrder(BaseModel):
    class State(models.TextChoices):
        PENDING = "PENDING", "Pendente de retorno"
        CLOSED = "CLOSED", "Encerrada"

    number = models.CharField(max_length=32, unique=True, editable=False, db_index=True)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="exit_orders")
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT, related_name="exit_orders")
    departed_at = models.DateTimeField()
    destination = models.CharField(max_length=255)
    reason = models.TextField()
    notes = models.TextField(blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING, db_index=True)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="exit_orders_opened")
    returned_at = models.DateTimeField(null=True, blank=True)
    return_notes = models.TextField(blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="exit_orders_closed")
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-departed_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle"],
                condition=Q(state="PENDING"),
                name="unique_pending_exit_order_per_vehicle",
            ),
        ]


class VehicleDriverAssignment(BaseModel):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="driver_assignments")
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT, related_name="vehicle_assignments")
    custody = models.ForeignKey(
        "VehicleCustody", null=True, blank=True, on_delete=models.PROTECT,
        related_name="assignments", verbose_name="Acautelamento",
    )
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


class VehicleCustody(BaseModel):
    """Acautelamento por viatura; ``assignment`` preserva o responsável inicial legado."""
    assignment = models.ForeignKey(
        VehicleDriverAssignment,
        on_delete=models.PROTECT,
        related_name="custodies",
    )
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="custodies")
    sei_number = models.CharField(
        "SEI do acautelamento",
        max_length=100,
    )
    started_on = models.DateField(
        "Início do acautelamento",
    )
    ended_on = models.DateField(
        "Fim do acautelamento",
        null=True,
        blank=True,
    )
    notes = models.TextField(
        "Observações",
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="vehicle_custodies_created",
    )
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="vehicle_custodies_ended",
    )

    class Meta:
        ordering = ["-started_on", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle"], condition=Q(ended_on__isnull=True),
                name="unique_open_custody_per_vehicle",
            ),
            models.CheckConstraint(
                condition=Q(ended_on__isnull=True) | Q(ended_on__gte=models.F("started_on")),
                name="custody_ended_on_after_started_on",
            ),
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


class BDT(BaseModel):
    """Registro operacional recebido do Hórus, identificado pela origem."""

    external_id = models.UUIDField(unique=True, db_index=True)
    vehicle = models.ForeignKey(
        Vehicle, null=True, blank=True, on_delete=models.PROTECT, related_name="bdts"
    )
    driver = models.ForeignKey(
        Driver, null=True, blank=True, on_delete=models.PROTECT, related_name="bdts"
    )
    horus_management_id = models.IntegerField(null=True, blank=True)
    horus_adm_id = models.UUIDField(null=True, blank=True)
    horus_service_id = models.UUIDField(null=True, blank=True)
    horus_sector_id = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    started_km = models.CharField(max_length=255, null=True, blank=True)
    ended_km = models.CharField(max_length=255, null=True, blank=True)
    latitude_match = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    longitude_match = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    latitude_retreat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    longitude_retreat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    departure_address = models.CharField(max_length=500, blank=True, default="")
    return_address = models.CharField(max_length=500, blank=True, default="")
    note = models.TextField(blank=True)
    horus_active = models.BooleanField(null=True, blank=True)
    management_name = models.CharField(max_length=150, blank=True)
    source_created_at = models.DateTimeField(null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_synced_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-started_at", "-created_at"]
        indexes = [
            models.Index(fields=["vehicle", "-started_at"]),
            models.Index(fields=["driver", "-started_at"]),
            models.Index(fields=["horus_management_id", "-started_at"]),
            models.Index(fields=["source_updated_at"]),
        ]

    @property
    def km_status(self):
        if self.started_km is None or self.ended_km is None:
            return "DADOS_INCOMPLETOS"
        started_km = normalize_km(self.started_km)
        ended_km = normalize_km(self.ended_km)
        if started_km is None or ended_km is None:
            return "FORMATO_INVALIDO"
        if ended_km < started_km:
            return "QUILOMETRAGEM_NEGATIVA"
        return "CALCULADA"

    @property
    def total_km(self):
        if self.km_status != "CALCULADA":
            return None
        return normalize_km(self.ended_km) - normalize_km(self.started_km)


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
    inspection_moment = models.CharField(
        max_length=10,
        choices=[
            ("SAIDA", "Saída"),
            ("RETORNO", "Retorno"),
            ("AVULSA", "Vistoria avulsa"),
        ],
        blank=True,
        default="",
    )
    checklist = models.JSONField(default=dict, blank=True)
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

class LicensingCalendar(BaseModel):
    exercise = models.PositiveSmallIntegerField(db_index=True)
    plate_final = models.PositiveSmallIntegerField()
    due_date = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="licensing_calendars_created")
    class Meta:
        ordering = ["-exercise", "plate_final"]
        constraints = [models.UniqueConstraint(fields=["exercise", "plate_final"], name="unique_licensing_calendar_exercise_plate_final"), models.CheckConstraint(condition=Q(plate_final__gte=0, plate_final__lte=9), name="licensing_plate_final_0_9")]

class VehicleCRLV(BaseModel):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="crlvs")
    document = models.OneToOneField(Document, on_delete=models.PROTECT, related_name="crlv_record")
    plate = models.CharField(max_length=8)
    renavam = models.CharField(max_length=20, blank=True)
    chassi = models.CharField(max_length=17, blank=True)
    exercise = models.PositiveSmallIntegerField(db_index=True)
    extracted_data = models.JSONField(default=dict, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="crlvs_confirmed")
    confirmed_at = models.DateTimeField(default=timezone.now)
    class Meta:
        ordering = ["-exercise", "-confirmed_at"]


class Maintenance(BaseModel):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="maintenances")
    workshop = models.ForeignKey(Workshop, null=True, blank=True, on_delete=models.PROTECT)
    type = models.ForeignKey(MaintenanceType, on_delete=models.PROTECT)
    status = models.ForeignKey(MaintenanceStatus, on_delete=models.PROTECT)
    mileage = models.PositiveIntegerField(null=True, blank=True)
    completion_mileage = models.PositiveIntegerField(null=True, blank=True)
    workshop_name = models.CharField(max_length=150, blank=True)
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

