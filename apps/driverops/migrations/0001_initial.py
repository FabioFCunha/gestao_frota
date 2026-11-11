import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("fleet", "0047_driver_document_identity"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(name="Company", fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("name", models.CharField(max_length=160)),
            ("active", models.BooleanField(default=True)),
        ], options={}),
        migrations.CreateModel(name="Member", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ("role", models.CharField(max_length=10, choices=[('driver', 'Motorista'), ('manager', 'Gestor')])),
            ("active", models.BooleanField(default=True)),
            ("company", models.ForeignKey(to='driverops.company', on_delete=django.db.models.deletion.PROTECT)),
            ("user", models.OneToOneField(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT)),
            ("driver", models.OneToOneField(to='fleet.driver', null=True, blank=True, on_delete=django.db.models.deletion.PROTECT)),
        ], options={}),
        migrations.CreateModel(name="CompanyVehicle", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ("company", models.ForeignKey(to='driverops.company', on_delete=django.db.models.deletion.PROTECT)),
            ("vehicle", models.OneToOneField(to='fleet.vehicle', on_delete=django.db.models.deletion.PROTECT)),
            ("label", models.CharField(max_length=100, help_text='Placa e identificação para o aplicativo')),
            ("drivers", models.ManyToManyField(to='driverops.member', blank=True)),
            ("active", models.BooleanField(default=True)),
        ], options={}),
        migrations.CreateModel(name="DeviceSession", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ("key_hash", models.CharField(max_length=64, unique=True)),
            ("expires_at", models.DateTimeField()),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("member", models.ForeignKey(to='driverops.member', on_delete=django.db.models.deletion.CASCADE)),
        ], options={}),
        migrations.CreateModel(name="Trip", fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("company", models.ForeignKey(to='driverops.company', on_delete=django.db.models.deletion.PROTECT)),
            ("member", models.ForeignKey(to='driverops.member', on_delete=django.db.models.deletion.PROTECT)),
            ("vehicle", models.ForeignKey(to='driverops.companyvehicle', on_delete=django.db.models.deletion.PROTECT)),
            ("exit_order", models.ForeignKey(to='fleet.vehicleexitorder', null=True, blank=True, on_delete=django.db.models.deletion.PROTECT)),
            ("opened_at", models.DateTimeField(auto_now_add=True)),
            ("closed_at", models.DateTimeField(null=True, blank=True)),
            ("closing_reason", models.TextField(blank=True)),
        ], options={"constraints": [models.UniqueConstraint(fields=["vehicle"], condition=models.Q(closed_at__isnull=True), name="driverops_vehicle_open_trip"), models.UniqueConstraint(fields=["member"], condition=models.Q(closed_at__isnull=True), name="driverops_member_open_trip")]}),
        migrations.CreateModel(name="Leg", fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("trip", models.ForeignKey(to='driverops.trip', related_name='legs', on_delete=django.db.models.deletion.PROTECT)),
            ("position", models.PositiveIntegerField()),
            ("destination", models.CharField(max_length=300)),
            ("started_at", models.DateTimeField(null=True, blank=True)),
            ("ended_at", models.DateTimeField(null=True, blank=True)),
            ("started_km", models.PositiveIntegerField(null=True, blank=True)),
            ("ended_km", models.PositiveIntegerField(null=True, blank=True)),
            ("departure_checklist", models.JSONField(default=dict)),
            ("arrival_checklist", models.JSONField(default=dict)),
            ("notes", models.TextField(blank=True)),
        ], options={"ordering": ["position"], "constraints": [models.UniqueConstraint(fields=["trip", "position"], name="driverops_leg_position"), models.UniqueConstraint(fields=["trip"], condition=models.Q(started_at__isnull=False, ended_at__isnull=True), name="driverops_one_active_leg")]}),
        migrations.CreateModel(name="Location", fields=[
            ("id", models.UUIDField(primary_key=True, editable=False, serialize=False)),
            ("leg", models.ForeignKey(to='driverops.leg', related_name='locations', on_delete=django.db.models.deletion.PROTECT)),
            ("measured_at", models.DateTimeField()),
            ("received_at", models.DateTimeField(auto_now_add=True)),
            ("latitude", models.FloatField()),
            ("longitude", models.FloatField()),
            ("accuracy", models.FloatField()),
        ], options={"ordering": ["measured_at", "id"]}),
        migrations.CreateModel(name="InspectionPhoto", fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("leg", models.ForeignKey(to='driverops.leg', related_name='photos', on_delete=django.db.models.deletion.PROTECT)),
            ("moment", models.CharField(max_length=10, choices=[('departure', 'Saída'), ('arrival', 'Chegada')])),
            ("image", models.BinaryField()),
            ("content_type", models.CharField(max_length=30)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
        ], options={}),
        migrations.CreateModel(name="Command", fields=[
            ("id", models.UUIDField(primary_key=True, editable=False, serialize=False)),
            ("member", models.ForeignKey(to='driverops.member', on_delete=django.db.models.deletion.PROTECT)),
            ("digest", models.CharField(max_length=64)),
            ("response", models.JSONField()),
            ("created_at", models.DateTimeField(auto_now_add=True)),
        ], options={}),
        migrations.CreateModel(name="Event", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ("trip", models.ForeignKey(to='driverops.trip', related_name='events', on_delete=django.db.models.deletion.PROTECT)),
            ("user", models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True, on_delete=django.db.models.deletion.SET_NULL)),
            ("action", models.CharField(max_length=50)),
            ("data", models.JSONField(default=dict)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
        ], options={}),
    ]
