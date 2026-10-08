import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

class Migration(migrations.Migration):
    dependencies = [("fleet", "0042_driver_sectors")]
    operations = [
        migrations.AddField(model_name="vehicle", name="crlv_exercise", field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Exercício do CRLV")),
        migrations.CreateModel(name="LicensingCalendar", fields=[("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)), ("active", models.BooleanField(default=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("exercise", models.PositiveSmallIntegerField(db_index=True)), ("plate_final", models.PositiveSmallIntegerField()), ("due_date", models.DateField()), ("notes", models.TextField(blank=True)), ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="licensing_calendars_created", to=settings.AUTH_USER_MODEL))], options={"ordering":["-exercise","plate_final"]}),
        migrations.CreateModel(name="VehicleCRLV", fields=[("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)), ("active", models.BooleanField(default=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("plate", models.CharField(max_length=8)), ("renavam", models.CharField(blank=True,max_length=20)), ("exercise",models.PositiveSmallIntegerField(db_index=True)), ("extracted_data",models.JSONField(blank=True,default=dict)), ("confirmed_at",models.DateTimeField(default=django.utils.timezone.now)), ("confirmed_by",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="crlvs_confirmed",to=settings.AUTH_USER_MODEL)), ("document",models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,related_name="crlv_record",to="fleet.document")), ("vehicle",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="crlvs",to="fleet.vehicle"))], options={"ordering":["-exercise","-confirmed_at"]}),
        migrations.AddConstraint(model_name="licensingcalendar", constraint=models.UniqueConstraint(fields=("exercise","plate_final"),name="unique_licensing_calendar_exercise_plate_final")),
        migrations.AddConstraint(model_name="licensingcalendar", constraint=models.CheckConstraint(condition=models.Q(("plate_final__gte",0),("plate_final__lte",9)),name="licensing_plate_final_0_9")),
    ]
