import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    auth_source = models.CharField(max_length=20, default="LOCAL")
    external_id = models.CharField(max_length=255, blank=True)
    last_changed_at = models.DateTimeField(auto_now=True)
