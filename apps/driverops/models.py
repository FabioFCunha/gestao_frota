import uuid
from django.conf import settings
from django.db import models, transaction
from django.db.models import Q


class Company(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Member(models.Model):
    DRIVER = "driver"
    MANAGER = "manager"
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    driver = models.OneToOneField("fleet.Driver", null=True, blank=True, on_delete=models.PROTECT)
    role = models.CharField(max_length=10, choices=[(DRIVER, "Motorista"), (MANAGER, "Gestor")])
    active = models.BooleanField(default=True)


    @transaction.atomic
    def save(self, *args, **kwargs):
        return super().save(*args, **kwargs)

class CompanyVehicle(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    vehicle = models.OneToOneField("fleet.Vehicle", on_delete=models.PROTECT)
    label = models.CharField(max_length=100, help_text="Placa e identificação para o aplicativo")
    drivers = models.ManyToManyField(Member, blank=True)
    active = models.BooleanField(default=True)


    def __str__(self):
        return self.label


    @transaction.atomic
    def save(self, *args, **kwargs):
        return super().save(*args, **kwargs)

class DeviceSession(models.Model):
    key_hash = models.CharField(max_length=64, unique=True)
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)


class Trip(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    member = models.ForeignKey(Member, on_delete=models.PROTECT)
    vehicle = models.ForeignKey(CompanyVehicle, on_delete=models.PROTECT)
    exit_order = models.ForeignKey("fleet.VehicleExitOrder", null=True, blank=True, on_delete=models.PROTECT)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closing_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["vehicle"], condition=Q(closed_at__isnull=True), name="driverops_vehicle_open_trip"),
            models.UniqueConstraint(fields=["member"], condition=Q(closed_at__isnull=True), name="driverops_member_open_trip"),
        ]


class Leg(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.ForeignKey(Trip, related_name="legs", on_delete=models.PROTECT)
    position = models.PositiveIntegerField()
    destination = models.CharField(max_length=300)
    destination_latitude = models.FloatField(null=True, blank=True)
    destination_longitude = models.FloatField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    started_km = models.PositiveIntegerField(null=True, blank=True)
    ended_km = models.PositiveIntegerField(null=True, blank=True)
    departure_checklist = models.JSONField(default=dict)
    arrival_checklist = models.JSONField(default=dict)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "position"], name="driverops_leg_position"),
            models.UniqueConstraint(fields=["trip"], condition=Q(started_at__isnull=False, ended_at__isnull=True), name="driverops_one_active_leg"),
        ]


class Location(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    leg = models.ForeignKey(Leg, related_name="locations", on_delete=models.PROTECT)
    measured_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    accuracy = models.FloatField()

    class Meta:
        ordering = ["measured_at", "id"]


class InspectionPhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    leg = models.ForeignKey(Leg, related_name="photos", on_delete=models.PROTECT)
    moment = models.CharField(max_length=10, choices=[("departure", "Saída"), ("arrival", "Chegada")])
    image = models.BinaryField()
    content_type = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)


class Command(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    member = models.ForeignKey(Member, on_delete=models.PROTECT)
    digest = models.CharField(max_length=64)
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class Event(models.Model):
    trip = models.ForeignKey(Trip, related_name="events", on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=50)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class RecordOwner(models.Model):
    """Company ownership for UUID-based records in the existing fleet schema."""
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='owned_records')
    model_label = models.CharField(max_length=100)
    object_id = models.UUIDField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['model_label','object_id'], name='driverops_record_one_company')]
        indexes = [models.Index(fields=['company','model_label'], name='driverops_owner_company_idx')]
