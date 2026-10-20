from django.db import migrations


GLOBAL = {'sector', 'brand', 'vehiclemodel', 'vehiclestatus', 'maintenancestatus',
          'maintenancetype', 'vehicleinspectiontype', 'vehicleinspectionstatus',
          'vehiclefinestatus', 'documenttype', 'documentstatus', 'seiprocessstatus', 'licensingcalendar'}
CHILDREN = {
    'vehicle': {'vehicleplate', 'vehiclemileage', 'vehicleinspection', 'vehiclefine', 'maintenance',
                'vehiclehistory', 'vehicledriverassignment', 'vehiclecustody', 'vehicleexitorder', 'vehiclecrlv', 'bdt'},
    'driver': {'drivercnhhistory'},
    'document': {'documentversion', 'documentrelation', 'vehiclecrlv'},
    'seiprocess': {'seiprocessrelation'},
}


def claim_existing(apps, schema_editor):
    alias = schema_editor.connection.alias
    Owner = apps.get_model('driverops', 'RecordOwner')
    CT = apps.get_model('contenttypes', 'ContentType')
    seen = set()

    def bind(model, pk, company):
        if pk is None or model._meta.model_name in GLOBAL:
            return
        key = (model._meta.label_lower, pk, company)
        if key in seen:
            return
        seen.add(key)
        record = model.objects.using(alias).get(pk=pk)
        owner, _ = Owner.objects.using(alias).get_or_create(
            model_label=model._meta.label_lower, object_id=pk, defaults={'company_id': company})
        if owner.company_id != company:
            raise RuntimeError('Um cadastro está vinculado a empresas diferentes. Reconcilie os vínculos antes da migração.')
        for field in model._meta.concrete_fields:
            if field.is_relation and field.remote_field.model._meta.app_label == 'fleet':
                bind(field.remote_field.model, getattr(record, field.attname), company)
        for related in model._meta.related_objects:
            if related.related_model._meta.app_label == 'fleet' and related.related_model._meta.model_name in CHILDREN.get(model._meta.model_name, set()) and not related.many_to_many:
                for child_pk in related.related_model.objects.using(alias).filter(**{related.field.attname: pk}).values_list('pk', flat=True):
                    bind(related.related_model, child_pk, company)
        ct = CT.objects.using(alias).filter(app_label='fleet', model=model._meta.model_name).first()
        if ct:
            for name in ('DocumentRelation', 'SEIProcessRelation'):
                relation = apps.get_model('fleet', name)
                for child_pk in relation.objects.using(alias).filter(content_type_id=ct.pk, object_id=pk).values_list('pk', flat=True):
                    bind(relation, child_pk, company)
        # Entity IDs are UUIDs; include historical extraction and edit audit entries.
        Audit = apps.get_model('fleet', 'AuditLog')
        if model != Audit:
            for audit_pk in Audit.objects.using(alias).filter(entity_id=pk).values_list('pk', flat=True):
                bind(Audit, audit_pk, company)

    for link in apps.get_model('driverops', 'CompanyVehicle').objects.using(alias).all():
        bind(apps.get_model('fleet', 'Vehicle'), link.vehicle_id, link.company_id)
    for member in apps.get_model('driverops', 'Member').objects.using(alias).exclude(driver_id=None):
        bind(apps.get_model('fleet', 'Driver'), member.driver_id, member.company_id)


class Migration(migrations.Migration):
    dependencies = [('driverops', '0002_recordowner'), ('fleet', '0047_driver_document_identity')]
    operations = [migrations.RunPython(claim_existing, migrations.RunPython.noop)]
