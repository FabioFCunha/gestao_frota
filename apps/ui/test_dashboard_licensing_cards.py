from datetime import date
from uuid import uuid4

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase
from django.template.loader import render_to_string


class CRLVOperationalCardsTemplateTests(SimpleTestCase):
    def render_dashboard(self, *, calendar_missing=None, pending=None):
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
                    "fines_pending": [],
                    "cnh_expired": [],
                },
                "licensing_summary": {
                    "pending": pending or [],
                    "pending_count": len(pending or []),
                    "calendar_missing_count": len(calendar_missing or []),
                },
                "crlv_alerts": {
                    "overdue": [],
                    "due_soon": [],
                    "pending_in_time": [],
                    "calendar_missing": calendar_missing or [],
                },
            },
            request=request,
        )

    def test_renders_licensing_pending_card_from_licensing_data(self):
        html = self.render_dashboard(
            pending=[
                {
                    "vehicle_id": str(uuid4()),
                    "plate": "TTO8A04",
                    "exercise": 2026,
                    "due_date": date(2026, 10, 1),
                    "dossier_url": "/veiculos/00000000-0000-0000-0000-000000000001/",
                    "status_label": "Vencido",
                }
            ]
        )

        self.assertIn("viatura(s) com licenciamento vencido", html)
        self.assertIn("viatura(s)", html)
        self.assertIn("Licenciamento vencido", html)
        self.assertIn("Vence nos próximos 30 dias", html)
        self.assertIn("Ver todas as 1 viaturas vencidas", html)
        self.assertIn("Abrir calendário anual", html)
        self.assertIn("TTO8A04", html)
        self.assertIn("crlv-overview-grid", html)
        self.assertIn("Vencido", html)
        self.assertIn('href="/calendario-licenciamento-rj/"', html)
        self.assertNotIn("Vistorias e multas", html)
        self.assertNotIn("Vistorias reprovadas/com ressalvas", html)

    def test_calendar_missing_details_are_kept_when_needed(self):
        html = self.render_dashboard(
            calendar_missing=[
                {
                    "vehicle_id": str(uuid4()),
                    "plate": "ABC1234",
                    "exercise": 2026,
                    "dossier_url": "/veiculos/00000000-0000-0000-0000-000000000001/",
                }
            ]
        )

        self.assertIn("Finais sem prazo cadastrado: 1 viatura(s)", html)
        self.assertIn("ABC1234", html)
        self.assertIn('href="/calendario-licenciamento-rj/"', html)
