from django.test import TestCase

from .forms import FleetAuthenticationForm
from .models import User


class AccountAccessTests(TestCase):
    def test_system_creator_is_identified_by_email(self):
        user = User.objects.create_user(
            username="fabiocunhaosp@gmail.com",
            email="fabiocunhaosp@gmail.com",
            password="StrongPass123!",
        )
        self.assertTrue(user.is_system_creator)

    def test_login_form_accepts_email_as_login(self):
        User.objects.create_user(
            username="usuario@teste.com",
            email="usuario@teste.com",
            password="StrongPass123!",
        )
        form = FleetAuthenticationForm(
            data={"username": "usuario@teste.com", "password": "StrongPass123!"}
        )
        self.assertTrue(form.is_valid())
