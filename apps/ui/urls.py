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
    path("veiculos/<uuid:pk>/ativo/", views.vehicle_set_active, name="vehicle_set_active"),
    path("veiculos/<uuid:pk>/posicao/", views.vehicle_position_edit, name="vehicle_position_edit"),
    path("bdts/", views.bdt_list, name="bdt_list"),
    path("veiculos/<uuid:pk>/", vehicle_dossier, name="vehicle_dossier"),
    path("veiculos/<uuid:pk>/crlv/", views.vehicle_crlv, name="vehicle_crlv"),
    path("calendario-licenciamento/", views.licensing_calendar_overview, name="licensing_calendar_overview"),
    path("calendario-licenciamento-rj/", views.licensing_calendar, name="licensing_calendar"),
    path("contratos/", contract_list, name="contract_list"),
    path("contratos/novo/", views.contract_create, name="contract_create"),
    path("contratos/<uuid:pk>/", contract_detail, name="contract_detail"),
    path("contratos/<uuid:pk>/editar/", views.contract_edit, name="contract_edit"),
    path("motoristas/", driver_list, name="driver_list"),
    path("motoristas/novo/", views.driver_create, name="driver_create"),
    path("motoristas/<uuid:pk>/cnh/", views.driver_cnh, name="driver_cnh"),
    path("motoristas/<uuid:pk>/editar/", views.driver_edit, name="driver_edit"),
    path("motoristas/<uuid:pk>/vincular-veiculo/", views.driver_assign_vehicle, name="driver_assign_vehicle"),
    path("manutencoes/", maintenance_list, name="maintenance_list"),
    path("manutencoes/nova/", views.maintenance_create, name="maintenance_create"),
    path("manutencoes/<uuid:pk>/revisao/", views.revision_action, name="revision_action"),
    path("manutencoes/importar-km/", views.km_import, name="km_import"),
    path("multas/", fine_list, name="fine_list"),
    path("multas/nova/", views.fine_create, name="fine_create"),
    path("multas/<uuid:pk>/editar/", views.fine_edit, name="fine_edit"),
    path("multas/<uuid:pk>/editar-dados/", views.fine_full_edit, name="fine_full_edit"),
    path("ordens-saida/", views.exit_order_list, name="exit_order_list"),
    path("ordens-saida/nova/", views.exit_order_create, name="exit_order_create"),
    path("ordens-saida/<uuid:pk>/", views.exit_order_detail, name="exit_order_detail"),
    path("ordens-saida/<uuid:pk>/retorno/", views.exit_order_return, name="exit_order_return"),
    path("veiculos/<uuid:pk>/contrato/", views.vehicle_contract_edit, name="vehicle_contract_edit"),
    path("veiculos/novo/", views.vehicle_create, name="vehicle_create"),
    path("veiculos/novo/cadastro-rapido/", views.vehicle_quick_create, name="vehicle_quick_create"),
    path("contratos/nova-locadora/", views.renter_quick_create, name="renter_quick_create"),
    path("oficinas/cadastro-rapido/", views.workshop_quick_create, name="workshop_quick_create"),
    path("entrar/", FleetLoginView.as_view(), name="login"),
    path("sair/", LogoutView.as_view(next_page="login"), name="logout"),
]


from django.urls import path as workshop_path
from .views import workshop_quick_create

urlpatterns += [
    workshop_path(
        "oficinas/cadastro-rapido/",
        workshop_quick_create,
        name="workshop_quick_create",
    ),
]

urlpatterns += [
    path(
        "manutencoes/tipos/cadastro-rapido/",
        views.maintenance_type_quick_create,
        name="maintenance_type_quick_create",
    ),
]

from .exit_order_edit import exit_order_edit

urlpatterns += [
    path(
        "ordens-saida/<uuid:pk>/editar/",
        exit_order_edit,
        name="exit_order_edit",
    ),
]


from .cnh_photo import cnh_photo_preview, driver_cnh_photo

urlpatterns += [
    path("cnh/<uuid:pk>/foto-previa/", cnh_photo_preview, name="cnh_photo_preview"),
    path("motoristas/<uuid:pk>/foto-cnh/", driver_cnh_photo, name="driver_cnh_photo"),
]

from .cnh_safety import cnh_original, identity_correction
urlpatterns += [
    path("cnh/<uuid:pk>/original/", cnh_original, name="cnh_original"),
    path("motoristas/<uuid:pk>/corrigir-cpf/", identity_correction, name="driver_identity_correction"),
]

from .cnh_imports import import_status, import_monitor
urlpatterns += [
    path("cnh/importacoes/", import_monitor, name="cnh_import_monitor"),
    path("cnh/importacoes/<uuid:pk>/", import_status, name="cnh_import_status"),
]
