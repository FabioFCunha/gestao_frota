from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from apps.fleet.vehicle_images import image_catalog


@login_required
def vehicle_image_credits(request):
    return render(request, 'ui/vehicle_image_credits.html', {'photos': image_catalog().values()})
