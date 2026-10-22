from io import StringIO
from unittest.mock import patch, Mock
from urllib.parse import urlparse, parse_qs
import requests
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings
from apps.fleet.vehicle_images import normalize_vehicle, url_imagem_veiculo, probe_image, classify_headers, _cached_url


@override_settings(IMAGIN_CUSTOMER_KEY='test-customer-not-real')
class VehicleImageTests(SimpleTestCase):
    def test_crlv_names_and_year(self):
        for make,model,expected in [('GM/CHEV','ONIX 10MT LT2',('chevrolet','onix',None)),
            ('Toyota','TOYOTA/COROLLA APREMIUMH',('toyota','corolla',None)),
            ('BYD','KING GS',('byd','king',None)),('VW','POLO MB',('volkswagen','polo',None))]:
            self.assertEqual(normalize_vehicle(make,model),expected)
        query = parse_qs(urlparse(url_imagem_veiculo('Toyota','Corolla',2026)).query)
        self.assertEqual(query, {'customer':['test-customer-not-real'], 'make':['toyota'],
            'modelFamily':['corolla'],'modelYear':['2026'],'angle':['23'],'zoomtype':['fullscreen']})
        self.assertNotIn('modelYear', parse_qs(urlparse(url_imagem_veiculo('BYD','King')).query))
        self.assertIsNone(url_imagem_veiculo('', 'King'))
        self.assertIsNone(url_imagem_veiculo('BYD', ''))

    def test_cache_and_no_network_during_url_generation(self):
        _cached_url.cache_clear()
        with patch('apps.fleet.vehicle_images.requests.head',side_effect=AssertionError('No network')):
            self.assertEqual(url_imagem_veiculo('GM','ONIX 10MT LT2'),url_imagem_veiculo('CHEV','Onix'))
        self.assertEqual(_cached_url.cache_info().misses,1)
        self.assertEqual(_cached_url.cache_info().hits,1)

    def test_placeholder_content_type_and_unknown_headers(self):
        headers={'Content-Type':'image/webp','X-ImaginStudio-Request-Found':'true','X-ImaginStudio-Request-Resolved':'true'}
        self.assertEqual(classify_headers(headers),'image')
        self.assertEqual(classify_headers({**headers,'X-ImaginStudio-Request-Found':'false'}),'placeholder')
        self.assertEqual(classify_headers({'Content-Type':'image/png'}),'unverified')
        self.assertEqual(classify_headers({'Content-Type':'text/html'}),'invalid_content_type')

    def test_remote_error_and_five_second_timeout(self):
        with patch('apps.fleet.vehicle_images.requests.head',side_effect=requests.Timeout) as head:
            self.assertEqual(probe_image('Toyota','Corolla'),'network_error')
            self.assertEqual(head.call_args.kwargs['timeout'],5)
        with patch('apps.fleet.vehicle_images.requests.head',return_value=Mock(status_code=403)):
            self.assertEqual(probe_image('BYD','King'),'http_403')

    @override_settings(IMAGIN_CUSTOMER_KEY='')
    def test_no_key_does_not_call_provider_and_samples_are_honest(self):
        with patch('apps.fleet.vehicle_images.requests.head') as head:
            self.assertIsNone(url_imagem_veiculo('Toyota','Corolla'))
            output=StringIO();call_command('check_vehicle_images',samples=True,stdout=output)
            self.assertEqual(output.getvalue().count('missing_customer_key'),3)
            head.assert_not_called()


from django.test import TestCase


@override_settings(IMAGIN_CUSTOMER_KEY='test-customer-not-real')
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
        with patch('apps.fleet.vehicle_images.requests.head',side_effect=AssertionError('No server CDN requests')):
            response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'modelFamily=onix')
        self.assertContains(response,'loading="lazy"')
        self.assertContains(response,'object-fit:contain')
        self.assertContains(response,'ABC1D23')
        self.assertContains(response,'Sem quilometragem registrada')

    @override_settings(IMAGIN_CUSTOMER_KEY='')
    def test_unconfigured_provider_keeps_dashboard_and_svg(self):
        response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Imagem indisponível: CHEV ONIX 10MT LT2')
        self.assertNotContains(response,'cdn.imagin.studio/getImage')
