import hashlib
import io
import json
import math
import secrets
import uuid
from datetime import timedelta
from PIL import Image, UnidentifiedImageError
from django.contrib.auth import authenticate
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from apps.fleet.models import VehicleMileage, VehicleExitOrder, Vehicle
from .authentication import DeviceAuthentication
from .models import Member, CompanyVehicle, DeviceSession, Trip, Leg, Location, Command, Event, InspectionPhoto

CHECKS = ("pneus", "luzes", "freios", "fluidos", "documentos", "equipamentos", "avarias", "limpeza")


class LoginThrottle(AnonRateThrottle):
    scope = "driver_login"


def member_for(request):
    member = Member.objects.select_related("company", "driver").filter(
        user=request.user, active=True, company__active=True
    ).first()
    if not member:
        raise PermissionDenied("Usuário sem vínculo ativo com uma empresa.")
    return member


def trip_data(trip):
    return {
        "id": str(trip.pk), "vehicle": trip.vehicle.label,
        "opened_at": trip.opened_at, "closed_at": trip.closed_at,
        "closing_reason": trip.closing_reason,
        "exit_order": str(trip.exit_order_id) if trip.exit_order_id else None,
        "legs": [{
            "id": str(leg.pk), "position": leg.position, "destination": leg.destination,
            "started_at": leg.started_at, "ended_at": leg.ended_at,
            "started_km": leg.started_km, "ended_km": leg.ended_km,
            "distance_km": leg.ended_km - leg.started_km if leg.ended_km is not None else None,
            "duration_seconds": int((leg.ended_at - leg.started_at).total_seconds()) if leg.ended_at else None,
            "departure_checklist": leg.departure_checklist,
            "arrival_checklist": leg.arrival_checklist, "notes": leg.notes,
        } for leg in trip.legs.all()]
    }


def owned_trip(member, pk, lock=False):
    query = Trip.objects.filter(company=member.company)
    if member.role != Member.MANAGER:
        query = query.filter(member=member)
    if lock:
        query = query.select_for_update()
    trip = query.filter(pk=pk).first()
    if not trip:
        raise PermissionDenied("BDT não disponível.")
    return trip


def positive_id(value):
    try:
        result = int(str(value))
        if result <= 0:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise ValidationError("Identificador de veículo inválido.")


def identifier(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise ValidationError("Identificador inválido.")


def km(value):
    if isinstance(value, bool):
        raise ValidationError("Informe o KM inteiro, entre 0 e 9999999.")
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        raise ValidationError("Informe o KM inteiro.")
    if not 0 <= number <= 9999999:
        raise ValidationError("KM fora do intervalo permitido.")
    return number


def checklist(data):
    if not isinstance(data, dict) or set(data) != set(CHECKS):
        raise ValidationError("Preencha todos os itens da vistoria.")
    for item in data.values():
        if not isinstance(item, dict) or item.get("status") not in ("ok", "problem", "na"):
            raise ValidationError("Situação inválida na vistoria.")
        note = item.get("note", "")
        if not isinstance(note, str) or len(note) > 2000:
            raise ValidationError("Observação inválida.")
        if item["status"] == "problem" and not note.strip():
            raise ValidationError("Descreva cada problema encontrado.")
    return data


def destinations(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 30:
        raise ValidationError("Cadastre entre 1 e 30 destinos.")
    if any(not isinstance(v, str) or not v.strip() or len(v.strip()) > 300 for v in values):
        raise ValidationError("Informe endereços de até 300 caracteres.")
    return [v.strip() for v in values]


def audit(request, trip, action, data):
    Event.objects.create(trip=trip, user=request.user, action=action, data=data)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login(request):
    username, password = request.data.get("username", ""), request.data.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ValidationError("Credenciais inválidas.")
    user = authenticate(request, username=username, password=password)
    if not user:
        return Response({"detail": "Usuário ou senha inválidos."}, status=401)
    member = Member.objects.filter(user=user, active=True, company__active=True).first()
    if not member or user.must_change_password:
        return Response({"detail": "Acesso indisponível. Verifique o vínculo e atualize a senha no portal."}, status=403)
    token = secrets.token_urlsafe(48)
    DeviceSession.objects.create(member=member, key_hash=hashlib.sha256(token.encode()).hexdigest(),
                                 expires_at=timezone.now() + timedelta(days=7))
    return Response({"token": token, "member_id": member.pk})


@api_view(["POST"])
@authentication_classes([DeviceAuthentication])
@permission_classes([IsAuthenticated])
def logout(request):
    request.auth.delete()
    return Response(status=204)


@api_view(["GET"])
@authentication_classes([DeviceAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def bootstrap(request):
    member = member_for(request)
    vehicles = CompanyVehicle.objects.filter(company=member.company, active=True, vehicle__active=True)
    if member.role != Member.MANAGER:
        vehicles = vehicles.filter(drivers=member)
    return Response({
        "name": request.user.get_full_name() or request.user.username,
        "company": member.company.name, "role": member.role,
        "checklist_items": CHECKS,
        "vehicles": [{"id": v.pk, "label": v.label,
                      "suggested_km": VehicleMileage.objects.filter(vehicle=v.vehicle).order_by("-date", "-created_at").values_list("mileage", flat=True).first()}
                     for v in vehicles],
        "active_trip": next((trip_data(t) for t in Trip.objects.filter(member=member, closed_at=None).select_related("vehicle")), None)
    })


@api_view(["GET", "POST"])
@authentication_classes([DeviceAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def trips(request):
    member = member_for(request)
    if request.method == "GET":
        query = Trip.objects.filter(company=member.company).select_related("vehicle").prefetch_related("legs")
        if member.role != Member.MANAGER:
            query = query.filter(member=member)
        return Response([trip_data(t) for t in query.order_by("-opened_at")[:100]])
    return execute(request, member, "create")


def execute(request, member, action, pk=None):
    if member.role != Member.DRIVER or not member.driver_id:
        raise PermissionDenied("Operação disponível somente para motorista vinculado.")
    try:
        command_id = uuid.UUID(str(request.headers.get("Idempotency-Key")))
    except (ValueError, TypeError):
        raise ValidationError("Envie Idempotency-Key com UUID para permitir repetição segura.")
    # DRF data must be plain JSON; photos have a separate authenticated endpoint.
    digest = hashlib.sha256(json.dumps(
        {"action": action, "pk": str(pk), "body": request.data},
        sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    with transaction.atomic():
        Member.objects.select_for_update().get(pk=member.pk)
        previous = Command.objects.filter(pk=command_id).first()
        if previous:
            if previous.member_id != member.pk or previous.digest != digest:
                raise ValidationError("Identificador de operação já utilizado.")
            return Response(previous.response)
        if action == "create":
            trip = create_trip(request, member)
        else:
            trip = owned_trip(member, pk, lock=True)
            if trip.closed_at:
                raise ValidationError("Este BDT já foi encerrado.")
            if action == "append":
                values = destinations(request.data.get("destinations"))
                offset = trip.legs.count()
                if offset + len(values) > 30:
                    raise ValidationError("Limite de 30 destinos por BDT.")
                Leg.objects.bulk_create([Leg(trip=trip, position=offset+i+1, destination=v) for i, v in enumerate(values)])
                audit(request, trip, "destinos_adicionados", {"destinations": values})
            elif action == "close":
                if trip.legs.filter(started_at__isnull=False, ended_at__isnull=True).exists():
                    raise ValidationError("Conclua o trecho ativo antes de encerrar.")
                reason = request.data.get("reason", "")
                if not isinstance(reason, str) or len(reason.strip()) < 5 or len(reason) > 2000:
                    raise ValidationError("Justifique o encerramento antecipado (5 a 2000 caracteres).")
                trip.closed_at, trip.closing_reason = timezone.now(), reason.strip()
                trip.save(update_fields=["closed_at", "closing_reason"])
                audit(request, trip, "encerramento_antecipado", {"reason": reason})
            else:
                transition(request, trip, action)
        # Convert datetimes once for durable JSON response and identical retries.
        from rest_framework.renderers import JSONRenderer
        result = json.loads(JSONRenderer().render(trip_data(trip)))
        Command.objects.create(id=command_id, member=member, digest=digest, response=result)
        return Response(result)


def create_trip(request, member):
    vehicle = CompanyVehicle.objects.select_for_update().filter(
        pk=positive_id(request.data.get("vehicle")), company=member.company, active=True,
        vehicle__active=True, drivers=member
    ).first()
    if not vehicle:
        raise PermissionDenied("Veículo não atribuído a este motorista.")
    Vehicle.objects.select_for_update().get(pk=vehicle.vehicle_id)
    if Trip.objects.filter(vehicle=vehicle, closed_at=None).exists() or Trip.objects.filter(member=member, closed_at=None).exists():
        raise ValidationError("Já existe BDT aberto para este motorista ou veículo.")
    values = destinations(request.data.get("destinations"))
    order = None
    if request.data.get("exit_order"):
        order = VehicleExitOrder.objects.filter(pk=identifier(request.data["exit_order"]), vehicle=vehicle.vehicle,
                                               driver=member.driver, state="PENDING").first()
        if not order:
            raise ValidationError("OS incompatível com o veículo, motorista ou situação.")
    trip = Trip.objects.create(company=member.company, member=member, vehicle=vehicle, exit_order=order)
    Leg.objects.bulk_create([Leg(trip=trip, position=i+1, destination=v) for i, v in enumerate(values)])
    audit(request, trip, "bdt_aberto", {"destinations": values})
    return trip


def transition(request, trip, action):
    leg = trip.legs.filter(pk=identifier(request.data.get("leg"))).first()
    if not leg:
        raise ValidationError("Trecho não encontrado.")
    Vehicle.objects.select_for_update().get(pk=trip.vehicle.vehicle_id)
    now = timezone.now()
    if action == "start":
        first = trip.legs.filter(ended_at=None).first()
        if not first or first.pk != leg.pk or leg.started_at:
            raise ValidationError("Inicie o próximo trecho pendente, na ordem dos destinos.")
        value = km(request.data.get("km"))
        last = trip.legs.filter(ended_at__isnull=False).order_by("-position").first()
        latest_km = VehicleMileage.objects.filter(vehicle=trip.vehicle.vehicle).order_by("-date", "-created_at").values_list("mileage", flat=True).first()
        minimum = max(last.ended_km if last else 0, latest_km or 0)
        if value < minimum:
            raise ValidationError(f"KM inicial deve ser igual ou superior a {minimum}.")
        leg.departure_checklist = checklist(request.data.get("checklist"))
        leg.started_at, leg.started_km = now, value
    elif action == "finish":
        if not leg.started_at or leg.ended_at:
            raise ValidationError("Somente trecho em andamento pode ser concluído.")
        value = km(request.data.get("km"))
        if value < leg.started_km:
            raise ValidationError("KM final não pode ser menor que o inicial.")
        leg.arrival_checklist = checklist(request.data.get("checklist"))
        notes = request.data.get("notes", "")
        if not isinstance(notes, str) or len(notes) > 2000:
            raise ValidationError("Observações devem ter até 2000 caracteres.")
        leg.ended_at, leg.ended_km, leg.notes = now, value, notes
        VehicleMileage.objects.create(
            vehicle=trip.vehicle.vehicle, mileage=value, date=now, origin="MANUAL",
            recorded_by=request.user, notes=f"App motorista: trecho {leg.pk}",
            external_id=f"MOBILE:{leg.pk}",
        )
    else:
        raise ValidationError("Operação inválida.")
    leg.save()
    audit(request, trip, "trecho_iniciado" if action == "start" else "trecho_concluido",
          {"leg": str(leg.pk), "km": value, "checklist": request.data["checklist"]})
    if action == "finish" and not trip.legs.filter(ended_at=None).exists():
        trip.closed_at = now
        trip.save(update_fields=["closed_at"])
        audit(request, trip, "bdt_encerrado", {})


@api_view(["POST"])
@authentication_classes([DeviceAuthentication])
@permission_classes([IsAuthenticated])
def operation(request, pk, action):
    if action not in ("start", "finish", "append", "close"):
        raise ValidationError("Operação inválida.")
    return execute(request, member_for(request), action, pk)


def parse_point(raw):
    if not isinstance(raw, dict):
        raise ValidationError("Posição inválida.")
    try:
        point_id = uuid.UUID(str(raw["id"]))
        measured = parse_datetime(raw["measured_at"])
        lat, lon, accuracy = float(raw["latitude"]), float(raw["longitude"]), float(raw["accuracy"])
        if not all(math.isfinite(v) for v in (lat, lon, accuracy)):
            raise ValueError
        if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not 0 <= accuracy <= 10000:
            raise ValueError
        if not measured or timezone.is_naive(measured):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValidationError("Coordenadas, precisão ou data da posição inválidas.")
    return point_id, measured, lat, lon, accuracy


@api_view(["POST"])
@authentication_classes([DeviceAuthentication])
@permission_classes([IsAuthenticated])
def locations(request, pk, leg_id):
    member = member_for(request)
    if member.role != Member.DRIVER:
        raise PermissionDenied()
    batch = request.data.get("points")
    if not isinstance(batch, list) or not 1 <= len(batch) <= 200:
        raise ValidationError("Envie de 1 a 200 posições.")
    with transaction.atomic():
        trip = owned_trip(member, pk, lock=True)
        leg = trip.legs.filter(pk=leg_id).first()
        if not leg or not leg.started_at:
            raise ValidationError("Trecho ainda não iniciado.")
        accepted, rejected = [], []
        for raw in batch:
            point_id, measured, lat, lon, accuracy = parse_point(raw)
            if measured < leg.started_at or measured > (leg.ended_at or timezone.now()):
                rejected.append({"id": str(point_id), "reason": "Posição fora do intervalo do trecho; confira o relógio do celular."})
                continue
            existing = Location.objects.filter(pk=point_id).first()
            if existing and (existing.leg_id != leg.pk or existing.measured_at != measured or
                             existing.latitude != lat or existing.longitude != lon or existing.accuracy != accuracy):
                raise ValidationError("Identificador de posição já utilizado.")
            if not existing:
                Location.objects.create(id=point_id, leg=leg, measured_at=measured,
                                        latitude=lat, longitude=lon, accuracy=accuracy)
            accepted.append(str(point_id))
    return Response({"accepted": accepted, "rejected": rejected})


@api_view(["GET"])
@authentication_classes([DeviceAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def detail(request, pk):
    member = member_for(request)
    trip = owned_trip(member, pk)
    data = trip_data(trip)
    data["events"] = [{"action": e.action, "at": e.created_at, "user": str(e.user_id), "data": e.data}
                      for e in trip.events.order_by("created_at")]
    data["photos"] = [{"id": str(p.pk), "leg": str(p.leg_id), "moment": p.moment}
                      for p in InspectionPhoto.objects.filter(leg__trip=trip)]
    return Response(data)


@api_view(["GET"])
@authentication_classes([DeviceAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def tracking(request, pk):
    member = member_for(request)
    trip = owned_trip(member, pk)
    points = Location.objects.filter(leg__trip=trip).order_by("-measured_at")[:1000]
    return Response({"server_time": timezone.now(), "points": [{
        "leg": str(p.leg_id), "latitude": p.latitude, "longitude": p.longitude,
        "accuracy": p.accuracy, "measured_at": p.measured_at, "received_at": p.received_at
    } for p in reversed(list(points))]})


@api_view(["POST"])
@authentication_classes([DeviceAuthentication])
@permission_classes([IsAuthenticated])
def upload_photo(request, pk, leg_id):
    member = member_for(request)
    trip = owned_trip(member, pk)
    if member.role != Member.DRIVER:
        raise PermissionDenied()
    leg = trip.legs.filter(pk=leg_id).first()
    moment, file = request.data.get("moment"), request.FILES.get("image")
    if not leg or moment not in ("departure", "arrival") or not file:
        raise ValidationError("Informe trecho, momento e imagem.")
    if file.size > 5 * 1024 * 1024:
        raise ValidationError("A foto deve ter até 5 MB.")
    raw = file.read()
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 16000000:
                raise ValidationError("Imagem deve ter até 16 megapixels.")
            image.load()
            image = image.convert("RGB")
            image.thumbnail((1920, 1920))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=85)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationError("Imagem inválida.")
    with transaction.atomic():
        Trip.objects.select_for_update().get(pk=trip.pk)
        if leg.photos.count() >= 20:
            raise ValidationError("Limite de 20 fotos por trecho.")
        photo = InspectionPhoto.objects.create(leg=leg, moment=moment, image=output.getvalue(), content_type="image/jpeg")
        audit(request, trip, "foto_vistoria", {"photo": str(photo.pk), "leg": str(leg.pk), "moment": moment})
    return Response({"id": str(photo.pk)}, status=201)


@api_view(["GET"])
@authentication_classes([DeviceAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def photo(request, photo_id):
    member = member_for(request)
    obj = InspectionPhoto.objects.select_related("leg__trip").filter(pk=photo_id, leg__trip__company=member.company).first()
    if not obj or (member.role != Member.MANAGER and obj.leg.trip.member_id != member.pk):
        raise PermissionDenied()
    response = HttpResponse(bytes(obj.image), content_type=obj.content_type)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
