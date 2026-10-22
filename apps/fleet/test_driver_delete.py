from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from apps.fleet.models import Driver, Sector, AuditLog


class LegacyDriverDeleteTests(TestCase):
    def test_sector_and_delete_permission_are_enforced(self):
        user = get_user_model().objects.create_superuser(username='exclusao-legado', email='exclusao@example.com', password='test')
        sector = Sector.objects.get_or_create(slug='adm', defaults={'name':'ADM'})[0]
        driver = Driver.objects.create(name='Motorista legado'); driver.sectors.add(sector)
        self.client.force_login(user)
        url = reverse('driver_delete', args=[driver.pk])+'?sector=adm'
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'confirmed':'on', 'reason':'Encerramento de atividades.'})
        self.assertEqual(response.status_code, 302)
        driver.refresh_from_db(); self.assertFalse(driver.active)
        self.assertTrue(AuditLog.objects.filter(entity_id=driver.pk, user=user).exists())
