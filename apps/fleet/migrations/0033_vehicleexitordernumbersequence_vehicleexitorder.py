# Generated manually after isolating the OS change from pre-existing migration drift.
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('fleet', '0032_vehicle_revision_reference'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='VehicleExitOrderNumberSequence',
            fields=[
                ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('value', models.PositiveBigIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='VehicleExitOrder',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('number', models.CharField(db_index=True, editable=False, max_length=32, unique=True)),
                ('departed_at', models.DateTimeField()),
                ('destination', models.CharField(max_length=255)),
                ('reason', models.TextField()),
                ('notes', models.TextField(blank=True)),
                ('state', models.CharField(choices=[('PENDING', 'Pendente de retorno'), ('CLOSED', 'Encerrada')], db_index=True, default='PENDING', max_length=16)),
                ('returned_at', models.DateTimeField(blank=True, null=True)),
                ('return_notes', models.TextField(blank=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('closed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='exit_orders_closed', to=settings.AUTH_USER_MODEL)),
                ('driver', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='exit_orders', to='fleet.driver')),
                ('opened_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='exit_orders_opened', to=settings.AUTH_USER_MODEL)),
                ('vehicle', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='exit_orders', to='fleet.vehicle')),
            ],
            options={'ordering': ['-departed_at', '-created_at']},
        ),
        migrations.AddConstraint(
            model_name='vehicleexitorder',
            constraint=models.UniqueConstraint(condition=models.Q(('state', 'PENDING')), fields=('vehicle',), name='unique_pending_exit_order_per_vehicle'),
        ),
    ]
