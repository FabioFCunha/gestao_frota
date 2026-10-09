from datetime import date
from uuid import uuid4

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase
from django.template.loader import render_to_string


class CRLVOperationalCardsTemplateTests(SimpleTestCase):
    def render_dashboard(self, *, calendar_missing=None):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        return render_to_string(
            "ui/dashboard.html",
            {
                "show_sector_filter": False,
                "requested_sector": "",
                "metrics": {"fleet": {"total": 2}},
                "plate_rows": [],
                "plate_alert_counts": {
                    "crlv_vencido": 0,
                    "revisao_vencida": 0,
                    "revisao_proxima": 0,
                    "manutencao": 0,
                    "multa": 0,
                    "contrato": 0,
                },
                "dashboard_alerts": {
                    "contracts_expired": [],
                    "contracts_expiring": [],
                    "fines_pending": [
                        {
                            "id": 1,
                            "vehicle__plate_history__plate": "TTO8A04",
                            "driver__name": "Motorista de teste",
                            "status__name": "Pendente",
                            "date": date(2026, 10, 1),
                        }
                    ],
                    "inspections_pending": [
                        {
                            "id": 2,
                            "vehicle_id": uuid4(),
                            "plate": "RJD1234",
                            "status": "Reprovada",
                            "date": date(2026, 10, 2),
                        }
                    ],
                    "cnh_expired": [],
                },
                "crlv_alerts": {
                    "overdue": [],
                    "due_soon": [],
                    "calendar_missing": calendar_missing or [],
                },
            },
            request=request,
        )

    def test_renders_inspection_and_fine_pending_actions(self):
        html = self.render_dashboard()

        self.assertIn("Vistorias e multas", html)
        self.assertIn("Vistorias reprovadas/com ressalvas", html)
        self.assertIn("RJD1234", html)
        self.assertIn("TTO8A04", html)
        self.assertIn('href="/vistorias/"', html)
        self.assertIn('href="/multas/"', html)

    def test_calendar_missing_details_are_kept_when_needed(self):
        html = self.render_dashboard(
            calendar_missing=[
                {
                    "plate": "ABC1234",
                    "exercise": 2026,
                    "dossier_url": "/veiculos/00000000-0000-0000-0000-000000000001/",
                }
            ]
        )

        self.assertIn("Finais sem prazo cadastrado: 1 viatura(s)", html)
        self.assertIn("ABC1234", html)
        self.assertIn('href="/calendario-licenciamento-rj/"', html)
