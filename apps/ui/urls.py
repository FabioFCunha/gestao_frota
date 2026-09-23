from django.contrib.auth.views import LogoutView
from django.urls import path
from .views import (
    FleetLoginView, dashboard, vehicle_list, vehicle_dossier,
    contract_list, contract_detail, driver_list, maintenance_list, fine_list
)
from apps.ui import views

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("veiculos/", vehicle_list, name="vehicle_list"),
    path("veiculos/<uuid:pk>/", vehicle_dossier, name="vehicle_dossier"),
    path("contratos/", contract_list, name="contract_list"),
    path("contratos/<uuid:pk>/", contract_detail, name="contract_detail"),
    path("motoristas/", driver_list, name="driver_list"),
    path("motoristas/novo/", views.driver_create, name="driver_create"),
    path("motoristas/<uuid:pk>/editar/", views.driver_edit, name="driver_edit"),
    path("motoristas/<uuid:pk>/vincular-veiculo/", views.driver_assign_vehicle, name="driver_assign_vehicle"),
    path("manutencoes/", maintenance_list, name="maintenance_list"),
    path("manutencoes/nova/", views.maintenance_create, name="maintenance_create"),
    path("manutencoes/importar-km/", views.km_import, name="km_import"),
    path("multas/", fine_list, name="fine_list"),
    path("multas/nova/", views.fine_create, name="fine_create"),
    path("veiculos/novo/", views.vehicle_create, name="vehicle_create"),
    path("entrar/", FleetLoginView.as_view(), name="login"),
    path("sair/", LogoutView.as_view(next_page="login"), name="logout"),
]
