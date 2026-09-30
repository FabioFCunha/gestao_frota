
import unittest
from decimal import Decimal

from apps.fleet.utils import normalize_km


class KMLogicTests(unittest.TestCase):

    def test_normalize_km_validos(self):
        # Inteiros
        self.assertEqual(normalize_km("54900"), Decimal("54900"))

        # Espaços como separador de milhar
        self.assertEqual(normalize_km("54 900"), Decimal("54900"))
        self.assertEqual(normalize_km("35 291"), Decimal("35291"))
        self.assertEqual(normalize_km("123 456"), Decimal("123456"))
        self.assertEqual(
            normalize_km("1 234 567"),
            Decimal("1234567"),
        )

        # Pontos como separador de milhar
        self.assertEqual(normalize_km("46.980"), Decimal("46980"))
        self.assertEqual(normalize_km("46.   980"), Decimal("46980"))
        self.assertEqual(normalize_km("123.456"), Decimal("123456"))
        self.assertEqual(
            normalize_km("1.234.567"),
            Decimal("1234567"),
        )
        self.assertEqual(
            normalize_km("1234.567"),
            Decimal("1234567"),
        )
        self.assertEqual(
            normalize_km("9.850"),
            Decimal("9850"),
        )

    def test_normalize_km_decimais_horus(self):
        self.assertEqual(normalize_km("10.5"), Decimal("10.5"))
        self.assertEqual(normalize_km("10.7"), Decimal("10.7"))
        self.assertEqual(normalize_km("10.8"), Decimal("10.8"))
        self.assertEqual(normalize_km("13.1"), Decimal("13.1"))
        self.assertEqual(normalize_km("35.7"), Decimal("35.7"))
        self.assertEqual(normalize_km("43.8"), Decimal("43.8"))
        self.assertEqual(normalize_km("77.0"), Decimal("77.0"))
        self.assertEqual(normalize_km("108.7"), Decimal("108.7"))
        self.assertEqual(normalize_km("214.8"), Decimal("214.8"))
        self.assertEqual(normalize_km("257.3"), Decimal("257.3"))
        self.assertEqual(normalize_km("480.3"), Decimal("480.3"))
        self.assertEqual(normalize_km("578.6"), Decimal("578.6"))
        self.assertEqual(normalize_km("788.8"), Decimal("788.8"))
        self.assertEqual(normalize_km("870.0"), Decimal("870.0"))
        self.assertEqual(normalize_km("935.3"), Decimal("935.3"))

    def test_normalize_km_decimais_com_duas_casas(self):
        self.assertEqual(normalize_km("40.00"), Decimal("40.00"))
        self.assertEqual(normalize_km("49.00"), Decimal("49.00"))
        self.assertEqual(normalize_km("59.00"), Decimal("59.00"))
        self.assertEqual(normalize_km("166.00"), Decimal("166.00"))
        self.assertEqual(normalize_km("650.00"), Decimal("650.00"))
        self.assertEqual(normalize_km("706.00"), Decimal("706.00"))

    def test_calculo_km_decimal(self):
        inicio = normalize_km("870.0")
        fim = normalize_km("935.3")

        self.assertEqual(
            fim - inicio,
            Decimal("65.3"),
        )

    def test_calculo_km_decimal_com_duas_casas(self):
        inicio = normalize_km("650.00")
        fim = normalize_km("706.00")

        self.assertEqual(
            fim - inicio,
            Decimal("56.00"),
        )

    def test_calculo_km_milhar(self):
        inicio = normalize_km("9.850")
        fim = normalize_km("9880")

        self.assertEqual(
            fim - inicio,
            Decimal("30"),
        )

    def test_normalize_km_invalidos_retornam_none(self):
        self.assertIsNone(normalize_km("1.2.3"))
        self.assertIsNone(normalize_km("12..34"))
        self.assertIsNone(normalize_km("ABC"))
        self.assertIsNone(normalize_km("20 341abc"))
        self.assertIsNone(normalize_km("50,5"))
        self.assertIsNone(normalize_km("-500"))
        self.assertIsNone(normalize_km(None))
        self.assertIsNone(normalize_km(""))
        self.assertIsNone(normalize_km("   "))

        # Três ou mais casas decimais permanecem ambíguas.
        self.assertIsNone(normalize_km("10.1234"))

