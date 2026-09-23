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
    last_changed_at = models.DateTimeField(auto_now=True)

    @property
    def is_system_creator(self):
        creator_email = getattr(settings, "SYSTEM_CREATOR_EMAIL", "fabiocunhaosp@gmail.com")
        return bool(self.email) and self.email.strip().casefold() == creator_email.strip().casefold()
