from unittest.mock import Mock, patch
import requests
from django.test import TestCase
from django.core.cache import cache
from rest_framework.test import APIClient
from . import tests as existing_tests
from .models import Trip


class AddressTests(TestCase):
    setUp = existing_tests.DriverAppTests.setUp
    login = existing_tests.DriverAppTests.login
    post = existing_tests.DriverAppTests.post

    @patch('apps.driverops.addresses.requests.get')
    def test_authenticated_suggestions_are_cached_and_do_not_send_account_data(self, get):
        get.return_value = Mock(status_code=200)
        get.return_value.json.return_value = {'features': [{
            'properties': {'name': 'Praça XV', 'city': 'Rio de Janeiro', 'state': 'Rio de Janeiro', 'countrycode': 'BR'},
            'geometry': {'coordinates': [-43.17, -22.9]},
        }]}
        for _ in range(2):
            response = self.client.get('/api/driver/addresses/', {'q': 'Praça XV Rio'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['results'][0]['latitude'], -22.9)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs['params'], {'q': 'Praça XV Rio', 'limit': 5, 'countrycode': 'BR'})
        self.assertNotIn('motorista', str(get.call_args))
        self.assertEqual(APIClient().get('/api/driver/addresses/?q=Rua+Brasil').status_code, 401)

    @patch('apps.driverops.addresses.requests.get', side_effect=requests.Timeout)
    def test_lookup_failure_keeps_manual_trip_creation_available(self, get):
        response = self.client.get('/api/driver/addresses/?q=Rua+Brasil')
        self.assertEqual(response.status_code, 503)
        response = self.post('trips/', {'vehicle': self.assignment.pk, 'destinations': ['Rua informada manualmente']})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['legs'][0]['destination_latitude'])

    def test_selected_coordinates_persist_on_create_append_and_retry(self):
        import uuid
        key = str(uuid.uuid4())
        payload = {'vehicle': self.assignment.pk, 'destinations': ['Praça XV'],
                   'destination_points': [{'latitude': -22.9, 'longitude': -43.17}]}
        first = self.post('trips/', payload, key)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.post('trips/', payload, key).data, first.data)
        response = self.post(f"trips/{first.data['id']}/append/", {'destinations': ['Base'],
            'destination_points': [{'latitude': 0, 'longitude': 0}]})
        self.assertEqual(response.status_code, 200)
        legs = response.data['legs']
        self.assertEqual(legs[0]['destination_longitude'], -43.17)
        self.assertEqual(legs[1]['destination_latitude'], 0)
        self.assertEqual(Trip.objects.get().legs.count(), 2)

    def test_invalid_or_misaligned_coordinates_do_not_create_partial_trip(self):
        for points in ([{'latitude': True, 'longitude': 10}], [], [{'latitude': 91, 'longitude': 0}]):
            response = self.post('trips/', {'vehicle': self.assignment.pk, 'destinations': ['Destino'],
                'destination_points': points})
            self.assertEqual(response.status_code, 400)
            self.assertFalse(Trip.objects.exists())

    @patch('apps.driverops.addresses.requests.get')
    def test_short_queries_and_rate_limit_do_not_reach_provider(self, get):
        self.assertEqual(self.client.get('/api/driver/addresses/?q=ab').status_code, 400)
        cache.set(f'throttle_driver_addresses_{self.user.pk}', [__import__('time').time()] * 30, 60)
        self.assertEqual(self.client.get('/api/driver/addresses/?q=Rua+Brasil').status_code, 429)
        get.assert_not_called()
