from datetime import date
from uuid import uuid4

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase
from django.template.loader import render_to_string


class CRLVOperationalCardsTemplateTests(SimpleTestCase):
    def render_dashboard(self, *, calendar_missing=None, overdue=None, due_soon=None):
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
                "licensing_summary": {"pending": [], "pending_count": 0, "calendar_missing_count": len(calendar_missing or [])},
                "crlv_alerts": {
                    "overdue": overdue or [],
                    "due_soon": due_soon or [],
                    "pending_in_time": [],
                    "calendar_missing": calendar_missing or [],
                },
            },
            request=request,
        )

    def test_renders_two_licensing_cards_with_vehicle_details(self):
        overdue = [{"vehicle_id": str(uuid4()), "plate": "TTO8A04", "exercise": 2026, "due_date": date(2026, 9, 30), "dossier_url": "/veiculos/00000000-0000-0000-0000-000000000001/"}]
        due_soon = [{"vehicle_id": str(uuid4()), "plate": "ABC1234", "exercise": 2026, "due_date": date(2026, 10, 15), "dossier_url": "/veiculos/00000000-0000-0000-0000-000000000002/"}]
        html = self.render_dashboard(overdue=overdue, due_soon=due_soon)

        self.assertIn("Licenciamento vencido", html)
        self.assertIn("Vence nos próximos 30 dias", html)
        self.assertIn("Ver todas as 1 viaturas vencidas", html)
        self.assertIn("Abrir calendário anual", html)
        self.assertIn("TTO8A04", html)
        self.assertIn("ABC1234", html)
        self.assertIn("30/09/2026", html)
        self.assertIn("15/10/2026", html)
        self.assertEqual(html.count("class=\"panel crlv-status-card\""), 2)
        self.assertIn('href="/calendario-licenciamento/"', html)
        self.assertNotIn("Situação dos licenciamentos", html)
        self.assertNotIn("Vistorias e multas", html)
        self.assertNotIn("Vistorias reprovadas/com ressalvas", html)

    def test_calendar_missing_details_are_kept_when_needed(self):
        calendar_missing = [{
            "vehicle_id": str(uuid4()),
            "plate": "ABC1234",
            "exercise": 2026,
            "dossier_url": "/veiculos/00000000-0000-0000-0000-000000000001/",
        }]
        html = self.render_dashboard(calendar_missing=calendar_missing)

        self.assertIn("Finais sem prazo cadastrado: 1 viatura(s)", html)
        self.assertIn("ABC1234", html)
        self.assertIn('href="/calendario-licenciamento-rj/"', html)



class LicensingCalendarOverviewTemplateTests(SimpleTestCase):
    def test_read_only_calendar_renders_deadlines_by_plate_final(self):
        html = render_to_string(
            "ui/licensing_calendar_overview.html",
            {
                "available_years": [2026, 2025],
                "selected_year": 2026,
                "calendar_count": 2,
                "finals": [
                    {"plate_final": 0, "due_date": date(2026, 9, 30), "notes": ""},
                    {"plate_final": 1, "due_date": date(2026, 10, 15), "notes": "Prazo oficial"},
                ] + [
                    {"plate_final": final, "due_date": None, "notes": ""}
                    for final in range(2, 10)
                ],
                "deadline_groups": [
                    {"due_date": date(2026, 9, 30), "notes": "", "plate_finals": [0], "plate_finals_label": "0"},
                    {"due_date": date(2026, 10, 15), "notes": "Prazo oficial", "plate_finals": [1], "plate_finals_label": "1"},
                ],
            },
        )
        self.assertIn("Calendário anual de licenciamento", html)
        self.assertIn("2026", html)
        self.assertIn("30/09/2026", html)
        self.assertIn("15/10/2026", html)
        self.assertIn("Final 0", html)
        self.assertIn("Final 1", html)
        self.assertIn("Voltar à central da frota", html)
        self.assertNotIn("Cadastrar prazo de licenciamento", html)
        self.assertNotIn("Editar grupo", html)
