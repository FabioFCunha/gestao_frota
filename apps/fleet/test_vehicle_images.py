from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.test import SimpleTestCase
from apps.fleet.vehicle_images import normalize_vehicle, url_imagem_veiculo, imagem_veiculo, probe_image, image_catalog


class VehicleImageTests(SimpleTestCase):
    def test_crlv_names_and_models(self):
        for make,model,expected in [('GM/CHEV','ONIX 10MT LT2',('chevrolet','onix',None)),
            ('Toyota','TOYOTA/COROLLA APREMIUMH',('toyota','corolla',None)),
            ('BYD','KING GS',('byd','king',None)),('VW','POLO MB',('volkswagen','polo',None))]:
            self.assertEqual(normalize_vehicle(make,model),expected)
        self.assertIsNone(url_imagem_veiculo('', 'King'))
        self.assertIsNone(url_imagem_veiculo('BYD', ''))
        self.assertIsNone(url_imagem_veiculo('Unknown', 'Unknown'))

    def test_curated_photos_are_available_and_fully_credited(self):
        for make,model in [('Toyota','Corolla'),('CHEV','ONIX 10MT LT2'),('BYD','King')]:
            item=imagem_veiculo(make,model,2026)
            self.assertTrue(item['author']);self.assertTrue(item['license'])
            self.assertTrue(item['source'].startswith('https://commons.wikimedia.org/'))
            self.assertTrue(item['license_url'].startswith('https://creativecommons.org/'))
            self.assertEqual(probe_image(make,model),'image')
            self.assertNotIn('customer=',item['url'])

    def test_lookup_never_calls_external_provider_and_reuses_catalog(self):
        image_catalog.cache_clear()
        with patch('requests.get',side_effect=AssertionError('No external request')):
            self.assertEqual(url_imagem_veiculo('GM','Onix'),url_imagem_veiculo('CHEV','ONIX 10MT LT2'))
        self.assertEqual(image_catalog.cache_info().misses,1)
        self.assertGreaterEqual(image_catalog.cache_info().hits,1)

    def test_uncredited_and_unsafe_catalog_entries_use_fallback(self):
        for item in [{'image':'../bad.jpg'}, {'image':'ui/vehicle_models/a.jpg'}]:
            with patch('apps.fleet.vehicle_images.image_catalog',return_value={'toyota/corolla':item}):
                self.assertIsNone(imagem_veiculo('Toyota','Corolla'))

    def test_samples_are_local_and_no_key_is_required(self):
        with patch('requests.get',side_effect=AssertionError('No external request')):
            output=StringIO();call_command('check_vehicle_images',samples=True,stdout=output)
        self.assertEqual(output.getvalue().count('"resultado": "image"'),3)
        self.assertEqual(probe_image('', 'Corolla'),'missing_data')
        self.assertEqual(probe_image('Toyota', 'Uncatalogued'),'missing_catalog')


from django.test import TestCase


class DashboardImageTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.fleet.models import Vehicle, VehicleStatus, VehiclePlate, Brand, VehicleModel, Sector
        self.user=get_user_model().objects.create_superuser(username='image-dashboard',email='images@example.com',password='test')
        sector=Sector.objects.get_or_create(slug='adm',defaults={'name':'ADM'})[0]
        brand=Brand.objects.create(name='CHEV'); model=VehicleModel.objects.create(brand=brand,name='ONIX 10MT LT2')
        status=VehicleStatus.objects.create(name='Disponível')
        self.vehicle=Vehicle.objects.create(brand=brand,model=model,status=status,sector=sector,model_year=2026)
        VehiclePlate.objects.create(vehicle=self.vehicle,plate='ABC1D23',kind='CURRENT')
        self.client.force_login(self.user)

    def test_dashboard_only_generates_urls_and_keeps_card_information(self):
        with patch('requests.get',side_effect=AssertionError('No server external requests')):
            response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'vehicle_models/chevrolet-onix.jpg')
        self.assertContains(response,'Créditos das fotos')
        self.assertContains(response,'loading="lazy"')
        self.assertContains(response,'object-fit:contain')
        self.assertContains(response,'ABC1D23')
        self.assertContains(response,'Sem quilometragem registrada')

    def test_unknown_model_keeps_dashboard_and_svg(self):
        self.vehicle.model = None
        self.vehicle.save(update_fields=['model'])
        response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Imagem indisponível: CHEV')
        self.assertNotContains(response,'cdn.imagin.studio/getImage')

    def test_photo_credits_show_authors_sources_and_licenses(self):
        from django.urls import reverse
        response=self.client.get(reverse('vehicle_image_credits'))
        self.assertEqual(response.status_code,200)
        for text in ['Mr.choppers','Heduardo55','User3204','CC0','CC BY-SA 3.0','CC BY-SA 4.0',
                     'commons.wikimedia.org','creativecommons.org']:
            self.assertContains(response,text)
