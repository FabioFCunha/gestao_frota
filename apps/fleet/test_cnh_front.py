from django.test import SimpleTestCase

from apps.fleet.cnh_front import extract_front_fields
from apps.fleet.cnh_legacy import _name


class FrontCNHFieldsTests(SimpleTestCase):
    def read(self, image, bounds):
        return {
            (.667, .604, .825, .647): "00345678901\n",
            (.462, .605, .638, .647): "123.456.789-09\n",
            (.462, .773, .975, .84): "JOSE DO MOTORISTA",
            (.462, .861, .975, .97): "MARIA DO MOTORISTA",
        }[bounds]

    def test_registration_keeps_leading_zeros_and_recovers_parent_fields(self):
        result = extract_front_fields(None, self.read)
        self.assertEqual(result, {
            "cnh_number": "00345678901", "cpf": "123.456.789-09",
            "father_name": "JOSE DO MOTORISTA", "mother_name": "MARIA DO MOTORISTA",
        })

    def test_one_parent_or_noisy_identity_is_not_guessed(self):
        def read(image, bounds):
            if bounds == (.462, .605, .638, .647):
                return "123.456.789-00"
            if bounds == (.462, .861, .975, .97):
                return ""
            if bounds == (.667, .604, .825, .647):
                return "003456789012"
            return self.read(image, bounds)
        self.assertEqual(extract_front_fields(None, read), {})

    def test_wrapped_surname_is_joined_without_joining_complete_names(self):
        self.assertEqual(_name("MARIA OLIVEIRA DA S\nILVA"), "MARIA OLIVEIRA DA SILVA")
        self.assertEqual(_name("MARIA DE FATIMA PER\nEIRA"), "MARIA DE FATIMA PEREIRA")
        self.assertEqual(_name("JOSE RUI\nALVES"), "JOSE RUI ALVES")

    def test_label_and_number_noise_cannot_become_parent_names(self):
        self.assertEqual(_name("MARIA DE TESTE\n123456"), "")
