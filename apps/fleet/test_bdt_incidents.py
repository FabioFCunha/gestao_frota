import unittest

from apps.fleet.bdt_incidents import detect_bdt_incident


class BDTIncidentTests(unittest.TestCase):
    def test_relatos_com_indicios(self):
        cases = {
            "O pneu furou na porta da Garagem": "Pneu ou roda",
            "Pneu traseiro direito estourou": "Pneu ou roda",
            "Houve colisão na saída": "Colisão ou acidente",
            "Veículo amassado no portão": "Avaria",
            "Princípio de incêndio": "Incêndio",
            "Veículo foi furtado": "Roubo ou furto",
            "Veículo atingido por alagamento": "Alagamento",
        }
        for note, category in cases.items():
            with self.subTest(note=note):
                self.assertIn(category, detect_bdt_incident(note)["categories"])

    def test_sem_indicio_ou_negacao(self):
        for note in (None, "", "Viatura em boas condições", "Sem sinistro",
                     "Não houve colisão", "Nenhuma avaria identificada",
                     "Sem avarias ou acidentes", "Troca preventiva de pneus",
                     "Não ocorreu furto", "Sem pneu furado"):
            with self.subTest(note=note):
                self.assertIsNone(detect_bdt_incident(note))

    def test_negacao_nao_apaga_outra_ocorrencia(self):
        result = detect_bdt_incident("Sem colisão, mas o pneu furou na garagem")
        self.assertEqual(result["categories"], ["Pneu ou roda"])

    def test_mais_de_uma_categoria(self):
        result = detect_bdt_incident("Colisão com veículo amassado e pneu estourado")
        self.assertEqual(len(result["categories"]), 3)
