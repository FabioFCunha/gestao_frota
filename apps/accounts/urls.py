from django.urls import path

from . import views


urlpatterns = [
    path("usuarios/", views.user_list, name="user_list"),
    path("usuarios/novo/", views.user_create, name="user_create"),
    path("usuarios/<uuid:pk>/editar/", views.user_edit, name="user_edit"),
    path("usuarios/<uuid:pk>/whatsapp/", views.user_whatsapp, name="user_whatsapp"),
    path("perfis/", views.group_list, name="group_list"),
    path("perfis/novo/", views.group_create, name="group_create"),
    path("perfis/<int:pk>/editar/", views.group_edit, name="group_edit"),
    path("ativar-conta/<uidb64>/<token>/", views.activate_account, name="activate_account"),
]
