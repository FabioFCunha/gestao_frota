"""Explicit ownership claims and reconciliation of records already linked in the pilot."""
from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.db import transaction
from apps.fleet.tenant_scope import GLOBAL, CATALOG, TenantModel, set_scope, reset_scope
from .models import RecordOwner, CompanyVehicle, Member


def claim(model, pk, company_id):
    if pk is None or model._meta.label_lower in GLOBAL:
        return
    obj, created = RecordOwner.objects.get_or_create(model_label=model._meta.label_lower,object_id=pk,
                                                   defaults={'company_id':company_id})
    if obj.company_id != company_id:
        raise PermissionDenied('Cadastro compartilhado por empresas diferentes. Reconcilie os vínculos antes de continuar.')


@transaction.atomic
def bind_graph(model, pk, company_id, seen=None):
    seen = set() if seen is None else seen
    key=(model._meta.label_lower,pk)
    if key in seen or model._meta.label_lower in GLOBAL | CATALOG:
        return
    seen.add(key)
    # Bypass only while reconciling a root explicitly associated by a platform administrator.
    token=set_scope(None)
    try:
        obj=model.objects.get(pk=pk)
        claim(model,pk,company_id)
        for field in model._meta.concrete_fields:
            if field.is_relation and field.remote_field.model._meta.app_label=='fleet':
                target=field.remote_field.model
                if issubclass(target,TenantModel) and getattr(obj,field.attname) is not None:
                    bind_graph(target,getattr(obj,field.attname),company_id,seen)
        # Child records are linked by actual FK, never guessed from dates or user names.
        child_models = {
            'vehicle': {'vehicleplate','vehiclemileage','vehicleinspection','vehiclefine','maintenance',
                        'vehiclehistory','vehicledriverassignment','vehiclecustody','vehicleexitorder','vehiclecrlv','bdt'},
            'driver': {'drivercnhhistory'},
            'document': {'documentversion','documentrelation','vehiclecrlv'},
            'seiprocess': {'seiprocessrelation'},
        }.get(model._meta.model_name,set())
        for related in model._meta.related_objects:
            if related.related_model._meta.model_name not in child_models:
                continue
            child=related.related_model
            if child._meta.app_label!='fleet' or not issubclass(child,TenantModel) or related.many_to_many:
                continue
            for child_id in child.objects.filter(**{related.field.attname:pk}).values_list('pk',flat=True):
                bind_graph(child,child_id,company_id,seen)
        from apps.fleet.models import DocumentRelation,SEIProcessRelation
        from django.contrib.contenttypes.models import ContentType
        ct=ContentType.objects.get_for_model(model)
        for relation_model in (DocumentRelation,SEIProcessRelation):
            for rel_id in relation_model.objects.filter(content_type=ct,object_id=pk).values_list('pk',flat=True):
                bind_graph(relation_model,rel_id,company_id,seen)
    finally:
        reset_scope(token)


def linked_vehicle(sender,instance,**kwargs):
    from apps.fleet.models import Vehicle
    bind_graph(Vehicle,instance.vehicle_id,instance.company_id)


def linked_driver(sender,instance,**kwargs):
    if instance.driver_id:
        from apps.fleet.models import Driver
        bind_graph(Driver,instance.driver_id,instance.company_id)


def validate_members(sender,instance,action,reverse,pk_set,**kwargs):
    if action!='pre_add':
        return
    if reverse:
        if CompanyVehicle.objects.filter(pk__in=pk_set).exclude(company_id=instance.company_id).exists():
            raise PermissionDenied('Veículos de outra empresa.')
    elif Member.objects.filter(pk__in=pk_set).exclude(company_id=instance.company_id,role='driver').exists():
        raise PermissionDenied('Selecione somente motoristas da empresa.')


def validate_fleet_m2m(sender,instance,action,reverse,pk_set,model,**kwargs):
    from apps.fleet.tenant_scope import current_scope
    if action=='pre_add' and current_scope() is not None and model._meta.app_label=='fleet':
        if model.objects.filter(pk__in=pk_set).count()!=len(pk_set):
            raise PermissionDenied('Vínculo de outra empresa.')


def fleet_saved(sender, instance, **kwargs):
    """Bridge normal fleet registrations into the driver's app, in the same transaction."""
    from apps.fleet.tenant_scope import company_id
    company = company_id()
    if kwargs.get('raw'):
        return
    if not company:
        # Offline imports may append children to an explicitly owned vehicle/driver.
        candidates = set(RecordOwner.objects.filter(model_label=sender._meta.label_lower, object_id=instance.pk).values_list("company_id", flat=True))
        for field in sender._meta.concrete_fields:
            if field.is_relation and field.remote_field.model._meta.app_label == 'fleet':
                label = field.remote_field.model._meta.label_lower
                if label not in GLOBAL | CATALOG:
                    candidates.update(RecordOwner.objects.filter(model_label=label, object_id=getattr(instance, field.attname)).values_list('company_id', flat=True))
        if len(candidates) > 1:
            raise PermissionDenied('Relações entre empresas diferentes.')
        if candidates:
            company = candidates.pop()
            bind_graph(sender, instance.pk, company)
        else:
            return
    from apps.fleet.models import Vehicle, VehiclePlate, VehicleDriverAssignment
    if sender is Vehicle:
        CompanyVehicle.objects.get_or_create(company_id=company, vehicle=instance,
                                            defaults={'label': 'Veículo cadastrado'})
    elif sender is VehiclePlate and instance.kind == 'CURRENT' and instance.ends_on is None:
        CompanyVehicle.objects.filter(company_id=company, vehicle_id=instance.vehicle_id).update(label=instance.plate)
    elif sender is VehicleDriverAssignment and instance.is_active and instance.ends_on is None:
        member = Member.objects.filter(company_id=company, driver_id=instance.driver_id, role=Member.DRIVER, active=True).first()
        link = CompanyVehicle.objects.filter(company_id=company, vehicle_id=instance.vehicle_id).first()
        if member and link:
            link.drivers.add(member)
