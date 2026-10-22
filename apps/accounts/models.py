import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    auth_source = models.CharField(max_length=20, default="LOCAL")
    external_id = models.CharField(max_length=255, blank=True)
    functional_id = models.CharField("ID funcional", max_length=50, unique=True, null=True, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=30, blank=True)
    must_change_password = models.BooleanField("Exigir troca de senha", default=False)
    last_changed_at = models.DateTimeField(auto_now=True)
    sectors = models.ManyToManyField('fleet.Sector', related_name='users', blank=True)

    @property
    def is_system_creator(self):
        creator_email = getattr(settings, "SYSTEM_CREATOR_EMAIL", "fabiocunhaosp@gmail.com")
        return bool(self.email) and self.email.strip().casefold() == creator_email.strip().casefold()

    def has_perm(self, perm, obj=None):
        # Company roles take precedence over permissions left in legacy groups.
        if getattr(settings, 'CENTRAL_USER_MANAGEMENT', False) and not self.is_superuser:
            from apps.fleet.tenant_scope import company_id
            if company_id():
                from apps.driverops.backends import CompanyManagerBackend
                return CompanyManagerBackend().has_perm(self, perm, obj)
        return super().has_perm(perm, obj)
