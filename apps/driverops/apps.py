from django.apps import AppConfig


class DriverOpsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.driverops"
    verbose_name = "Aplicativo do motorista"

    def ready(self):
        from django.apps import apps
        from django.db.models.signals import post_save, m2m_changed
        from apps.fleet.tenant_scope import TenantModel
        from .models import CompanyVehicle, Member
        from .ownership import linked_vehicle, linked_driver, validate_members, validate_fleet_m2m, fleet_saved
        post_save.connect(linked_vehicle,sender=CompanyVehicle,dispatch_uid='driverops_vehicle_owner')
        post_save.connect(linked_driver,sender=Member,dispatch_uid='driverops_driver_owner')
        m2m_changed.connect(validate_members,sender=CompanyVehicle.drivers.through,dispatch_uid='driverops_member_company')
        for model in apps.get_app_config('fleet').get_models():
            if issubclass(model,TenantModel):
                # Related descriptors must use the same lazy scope as public queries.
                model._meta.__dict__['base_manager'] = model.objects
                post_save.connect(fleet_saved, sender=model, dispatch_uid='driverops_bridge_'+model._meta.label_lower)
            for field in model._meta.local_many_to_many:
                m2m_changed.connect(validate_fleet_m2m,sender=field.remote_field.through,
                                    dispatch_uid='driverops_m2m_'+field.remote_field.through._meta.label_lower)
