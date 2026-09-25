from django.test import TestCase
from django.urls import reverse

from .forms import FleetAuthenticationForm, UserForm
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

    def test_user_form_requires_initial_password_for_new_user(self):
        form = UserForm(
            data={
                "first_name": "Usuário",
                "last_name": "",
                "email": "novo@teste.com",
                "functional_id": "123456",
                "whatsapp": "21999999999",
                "groups": [],
                "is_active": True,
                "initial_password": "",
                "initial_password_confirmation": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("initial_password", form.errors)

    def test_user_with_initial_password_must_change_on_first_access(self):
        user = User.objects.create_user(
            username="usuario@teste.com",
            email="usuario@teste.com",
            password="SenhaInicial123!",
            is_active=True,
            must_change_password=True,
        )

        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, reverse("password_change"))

    def test_password_change_clears_mandatory_flag(self):
        user = User.objects.create_user(
            username="usuario@teste.com",
            email="usuario@teste.com",
            password="SenhaInicial123!",
            is_active=True,
            must_change_password=True,
        )

        self.client.force_login(user)
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "SenhaInicial123!",
                "new_password1": "SenhaNova123!",
                "new_password2": "SenhaNova123!",
            },
        )

        self.assertRedirects(response, "/")
        user.refresh_from_db()
        self.assertFalse(user.must_change_password)
        self.assertTrue(user.check_password("SenhaNova123!"))
