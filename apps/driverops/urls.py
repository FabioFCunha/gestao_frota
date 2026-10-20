from django.urls import path
from . import views
from .portal import dashboard

app_name = "driverops"
urlpatterns = [
    path("panel/", dashboard),
    path("login/", views.login),
    path("logout/", views.logout),
    path("bootstrap/", views.bootstrap),
    path("trips/", views.trips),
    path("trips/<uuid:pk>/", views.detail),
    path("trips/<uuid:pk>/tracking/", views.tracking),
    path("trips/<uuid:pk>/legs/<uuid:leg_id>/locations/", views.locations),
    path("trips/<uuid:pk>/legs/<uuid:leg_id>/photos/", views.upload_photo),
    path("trips/<uuid:pk>/<str:action>/", views.operation),
    path("photos/<uuid:photo_id>/", views.photo),
]
