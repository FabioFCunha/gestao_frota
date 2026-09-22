from django.contrib import admin
from . import models

for model in [models.VehicleStatus, models.Renter, models.AdministrativeUnit, models.Base, models.Brand, models.VehicleModel, models.Driver, models.Contract, models.Vehicle, models.VehiclePlate, models.MaintenanceStatus, models.MaintenanceType, models.Workshop, models.Maintenance, models.VehicleHistory, models.AuditLog]:
    admin.site.register(model)
