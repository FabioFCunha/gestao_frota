import re

from django.db import transaction
from django.db import models
from .models import AuditLog, Driver, Maintenance, VehicleHistory, VehicleStatus, VehicleDriverAssignment, VehicleCustody, Vehicle


# === WW TRANS: REGRA DE REVISÃO PREVENTIVA ===

REVISION_INTERVAL_KM = 10_000
REVISION_ALERT_KM = 3_000


def get_vehicle_revision_status(*, vehicle):
    """
    Calcula a situação da revisão preventiva do veículo.

    A próxima revisão é sempre 10.000 km após a última revisão
    efetivamente concluída e registrada com quilometragem.

    Apenas manutenções:
      - do tipo "Revisão";
      - com status "Concluída";
      - com KM informado

    podem estabelecer uma nova referência.

    Para veículos legados sem manutenção de revisão registrada, utiliza a
    referência ``[KM_PROX_REVISAO]`` armazenada nas observações do veículo.
    """
    from .models import MaintenanceType, MaintenanceStatus, VehicleMileage

    revision_type = MaintenanceType.objects.filter(
        name__iexact="Revisão",
        active=True,
    ).first()

    completed_status = MaintenanceStatus.objects.filter(
        name__iexact="Concluída",
        active=True,
    ).first()

    latest_mileage = (
        VehicleMileage.objects.filter(vehicle=vehicle)
        .order_by("-date", "-created_at").first()
    )
    current_mileage = latest_mileage.mileage if latest_mileage else None

    active_revision = None

    if revision_type:
        active_revision = (
            Maintenance.objects
            .filter(
                vehicle=vehicle,
                type=revision_type,
                exited_at__isnull=True,
                status__name__in=["Aberta", "Em andamento"],
            )
            .order_by("-entered_at", "-created_at")
            .first()
        )

    last_revision = None

    if revision_type and completed_status:
        last_revision = (
            Maintenance.objects
            .filter(
                vehicle=vehicle,
                type=revision_type,
                status=completed_status,
            )
            .filter(
                models.Q(completion_mileage__isnull=False)
                | models.Q(mileage__isnull=False)
            )
            .order_by(
                models.F("completion_mileage").desc(nulls_last=True),
                "-mileage",
                "-entered_at",
                "-created_at",
            )
            .first()
        )

    if last_revision:
        last_revision_km = (
            last_revision.completion_mileage
            if last_revision.completion_mileage is not None
            else last_revision.mileage
        )
        next_revision_km = last_revision_km + REVISION_INTERVAL_KM
        has_history = True
    else:
        legacy_reference = re.search(
            r"\[KM_PROX_REVISAO\]\s*(\d+)",
            vehicle.notes or "",
        )
        if legacy_reference:
            last_revision_km = None
            next_revision_km = int(legacy_reference.group(1))
            has_history = False
        elif vehicle.revision_reference_km is not None:
            last_revision_km = vehicle.revision_reference_km
            next_revision_km = last_revision_km + REVISION_INTERVAL_KM
            has_history = False
        elif current_mileage is None:
            return {
                "last_revision_id": None,
                "last_revision_km": None,
                "last_revision_entered_at": None,
                "last_revision_exited_at": None,
                "last_revision_workshop": "",
                "last_revision_workshop_name": "",
                "last_revision_service": "",
                "last_revision_completion_mileage": None,
                "next_revision_km": None,
                "current_km": current_mileage,
                "km_remaining": None,
                "status": "SEM_QUILOMETRAGEM",
                "has_history": False,
            }

        else:
            # A primeira referência deve ser criada explicitamente pelo
            # comando de inicialização ou no fluxo que grava a leitura; a
            # consulta jamais grava e nunca usa "KM atual + intervalo".
            return {
                "last_revision_id": None,
                "last_revision_km": None,
                "last_revision_entered_at": None,
                "last_revision_exited_at": None,
                "last_revision_workshop": "",
                "last_revision_workshop_name": "",
                "last_revision_service": "",
                "last_revision_completion_mileage": None,
                "next_revision_km": None,
                "current_km": current_mileage,
                "km_remaining": None,
                "status": "SEM_HISTORICO",
                "has_history": False,
                "reference_initialization_required": True,
            }

    km_remaining = next_revision_km - current_mileage

    if active_revision:
        status = "EM_REVISAO"
    elif km_remaining <= 0:
        status = "DEVIDA"
    elif km_remaining <= REVISION_ALERT_KM:
        status = "PROXIMA"
    else:
        status = "OK"

    return {
        "last_revision_id": last_revision.id if last_revision else None,
        "last_revision_km": last_revision_km,
        "last_revision_entered_at": last_revision.entered_at if last_revision else None,
        "last_revision_exited_at": last_revision.exited_at if last_revision else None,
        "last_revision_workshop": last_revision.workshop.name if last_revision and last_revision.workshop else "",
        "last_revision_workshop_name": last_revision.workshop_name if last_revision else "",
        "last_revision_service": last_revision.service if last_revision else "",
        "last_revision_completion_mileage": last_revision.completion_mileage if last_revision else None,
        "active_revision_id": active_revision.id if active_revision else None,
        "active_revision_entered_at": active_revision.entered_at if active_revision else None,
        "next_revision_km": next_revision_km,
        "current_km": current_mileage,
        "km_remaining": km_remaining,
        "status": status,
        "has_history": has_history,
    }


@transaction.atomic
def change_vehicle_status(*, vehicle: Vehicle, status_name: str, user, reason: str = ""):
    try:
        target_status = VehicleStatus.objects.get(name__iexact=status_name, active=True)
    except VehicleStatus.DoesNotExist:
        raise ValueError(f"Status '{status_name}' inválido ou inativo.")

    previous = vehicle.status

    if previous and previous.id == target_status.id:
        return vehicle

    old_value = {"id": str(previous.id), "name": previous.name} if previous else None
    new_value = {"id": str(target_status.id), "name": target_status.name}

    vehicle.status = target_status
    vehicle.save(update_fields=["status", "updated_at"])

    VehicleHistory.objects.create(
        vehicle=vehicle,
        field="status",
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        changed_by=user
    )

    AuditLog.objects.create(
        user=user,
        module="veículos",
        action="ALTERAÇÃO DE STATUS",
        entity_type="vehicle",
        entity_id=vehicle.id,
        old_values={"status": previous.name if previous else None},
        new_values={"status": target_status.name},
        reason=reason
    )

    return vehicle


def _next_exit_order_number():
    """Returns the next OS number while holding the single counter row lock."""
    from django.db import IntegrityError
    from .models import VehicleExitOrderNumberSequence

    try:
        sequence = VehicleExitOrderNumberSequence.objects.select_for_update().get(pk=1)
    except VehicleExitOrderNumberSequence.DoesNotExist:
        try:
            # A savepoint keeps the outer opening transaction usable if another
            # request creates the singleton counter first.
            with transaction.atomic():
                VehicleExitOrderNumberSequence.objects.create(pk=1, value=0)
        except IntegrityError:
            pass
        sequence = VehicleExitOrderNumberSequence.objects.select_for_update().get(pk=1)
    sequence.value += 1
    sequence.save(update_fields=["value"])
    return f"OS-{sequence.value:06d}"


@transaction.atomic
def open_vehicle_exit_order(*, vehicle_id, driver, departed_at, destination, reason, notes, user):
    from django.db import IntegrityError
    from .sector_scope import validate_vehicle_scope
    from .models import VehicleExitOrder

    vehicle = Vehicle.objects.select_for_update().get(pk=vehicle_id)
    validate_vehicle_scope(user, vehicle)
    vehicle = Vehicle.objects.select_for_update().get(pk=vehicle.pk)
    ensure_vehicle_active(vehicle)
    if VehicleExitOrder.objects.filter(vehicle=vehicle, state=VehicleExitOrder.State.PENDING).exists():
        raise ValueError("Esta viatura já possui uma OS pendente de retorno.")

    try:
        # The partial unique constraint is the final authority when two
        # requests pass the pre-check concurrently.
        with transaction.atomic():
            order = VehicleExitOrder.objects.create(
                number=_next_exit_order_number(), vehicle=vehicle, driver=driver,
                departed_at=departed_at, destination=destination, reason=reason,
                notes=notes, opened_by=user,
            )
    except IntegrityError as exc:
        raise ValueError("Esta viatura já possui uma OS pendente de retorno.") from exc
    AuditLog.objects.create(
        user=user, module="ordens de saída", action="ABERTURA OS SAÍDA",
        entity_type="vehicle_exit_order", entity_id=order.id,
        new_values={"number": order.number, "vehicle_id": str(vehicle.id), "state": order.state},
        reason=f"Abertura da {order.number}.",
    )
    return order


@transaction.atomic
def close_vehicle_exit_order(*, order_id, returned_at, return_notes, user):
    from django.core.exceptions import PermissionDenied
    from .models import VehicleExitOrder

    order = VehicleExitOrder.objects.select_for_update().get(pk=order_id)
    if order.opened_by_id != user.id:
        raise PermissionDenied("Somente o usuário que abriu a OS pode registrar o retorno.")
    if order.state == VehicleExitOrder.State.CLOSED:
        raise ValueError("Esta OS já foi encerrada.")
    if returned_at < order.departed_at:
        raise ValueError("O retorno não pode ser anterior à saída.")

    order.state = VehicleExitOrder.State.CLOSED
    order.returned_at = returned_at
    order.return_notes = return_notes
    order.closed_by = user
    from django.utils import timezone
    order.closed_at = timezone.now()
    order.save(update_fields=["state", "returned_at", "return_notes", "closed_by", "closed_at", "updated_at"])
    AuditLog.objects.create(
        user=user, module="ordens de saída", action="ENCERRAMENTO OS SAÍDA",
        entity_type="vehicle_exit_order", entity_id=order.id,
        old_values={"state": VehicleExitOrder.State.PENDING},
        new_values={"state": order.state, "returned_at": order.returned_at.isoformat()},
        reason=f"Encerramento da {order.number}.",
    )
    return order


@transaction.atomic
def open_maintenance(*, maintenance: Maintenance, user):
    """Applies the mandatory backend transition caused by opening maintenance."""
    if maintenance.status.name.casefold() != "aberta":
        return maintenance
        
    vehicle = maintenance.vehicle
    ensure_vehicle_active(vehicle)
    
    # Previne múltiplas manutenções operacionais simultâneas.
    # "Aberta" e "Em andamento" ocupam a manuten??o operacional do veículo.
    existing_active = Maintenance.objects.filter(
        vehicle=vehicle,
        status__name__in=["Aberta", "Em andamento"]
    ).exclude(id=maintenance.id).exists()

    if existing_active:
        raise ValueError(
            "O veículo já possui uma manuten??o aberta ou em andamento. "
            "Conclua ou cancele a atual antes de abrir outra."
        )
        
    previous = vehicle.status
    
    maintenance.vehicle_status_before_opening = previous
    maintenance.opened_by = user
    maintenance.save(update_fields=["vehicle_status_before_opening", "opened_by", "updated_at"])
    
    change_vehicle_status(
        vehicle=vehicle, 
        status_name="Em manutenção", 
        user=user, 
        reason="Abertura de manutenção"
    )
    
    return maintenance

@transaction.atomic
def complete_maintenance(
    *,
    maintenance: Maintenance,
    user,
    resulting_status: str = None,
    reason: str = "",
    completion_mileage: int = None,
    exited_at=None,
    allow_already_completed: bool = False,
):
    if not resulting_status:
        raise ValueError("O status resultante do veículo deve ser explicitamente informado ao concluir a manutenção.")
        
    current_status = maintenance.status.name.casefold()
    if current_status == "cancelada":
        raise ValueError(f"Não é possível concluir uma manutenção que já está {current_status}.")
    if current_status == "concluída" and not allow_already_completed:
        raise ValueError(f"Não é possível concluir uma manutenção que já está {current_status}.")
        
    try:
        from .models import MaintenanceStatus
        concluida_status = MaintenanceStatus.objects.get(name__iexact="Concluída", active=True)
    except MaintenanceStatus.DoesNotExist:
        raise ValueError("Status de manutenção 'Concluída' não encontrado no sistema.")
        
    from django.utils import timezone
    now = timezone.now()
    exit_timestamp = exited_at or now
    
    if maintenance.entered_at and exit_timestamp < maintenance.entered_at:
        raise ValueError("A data de retorno não pode ser anterior à data de envio para revisão.")
    
    old_status_name = maintenance.status.name

    if completion_mileage is not None:
        completion_mileage = int(completion_mileage)
        if completion_mileage < 0:
            raise ValueError("A quilometragem de retorno não pode ser negativa.")
        if maintenance.mileage is not None and completion_mileage < maintenance.mileage:
            raise ValueError("A quilometragem de retorno não pode ser menor que a quilometragem de entrada.")
        maintenance.completion_mileage = completion_mileage

    maintenance.status = concluida_status
    maintenance.exited_at = exit_timestamp
    maintenance.resolved_by = user
    update_fields = ["status", "exited_at", "resolved_by", "updated_at"]
    if completion_mileage is not None:
        update_fields.append("completion_mileage")
    maintenance.save(update_fields=update_fields)
    
    if completion_mileage is not None:
        record_vehicle_mileage(
            vehicle=maintenance.vehicle,
            mileage=completion_mileage,
            user=user,
            origin="MANUAL",
            notes=f"Retorno da revisão #{maintenance.id}",
        )

    AuditLog.objects.create(
        user=user,
        module="manutenções",
        action="CONCLUSÃO",
        entity_type="maintenance",
        entity_id=maintenance.id,
        old_values={"status": old_status_name},
        new_values={"status": concluida_status.name},
        reason=reason or "Manutenção concluída"
    )
    
    change_vehicle_status(
        vehicle=maintenance.vehicle,
        status_name=resulting_status,
        user=user,
        reason=reason or "Retorno de manutenção"
    )
    
    return maintenance

@transaction.atomic
def cancel_maintenance(*, maintenance: Maintenance, user, resulting_status: str = None, reason: str = ""):
    if not resulting_status:
        raise ValueError("O status resultante do veículo deve ser explicitamente informado ao cancelar a manutenção.")
        
    current_status = maintenance.status.name.casefold()
    if current_status in ["concluída", "cancelada"]:
        raise ValueError(f"Não é possível cancelar uma manutenção que já está {current_status}.")
        
    try:
        from .models import MaintenanceStatus
        cancelada_status = MaintenanceStatus.objects.get(name__iexact="Cancelada", active=True)
    except MaintenanceStatus.DoesNotExist:
        raise ValueError("Status de manutenção 'Cancelada' não encontrado no sistema.")
        
    from django.utils import timezone
    now = timezone.now()
    
    old_status_name = maintenance.status.name
    
    maintenance.status = cancelada_status
    maintenance.exited_at = now
    maintenance.resolved_by = user
    maintenance.save(update_fields=["status", "exited_at", "resolved_by", "updated_at"])
    
    AuditLog.objects.create(
        user=user,
        module="manutenções",
        action="CANCELAMENTO",
        entity_type="maintenance",
        entity_id=maintenance.id,
        old_values={"status": old_status_name},
        new_values={"status": cancelada_status.name},
        reason=reason or "Manutenção cancelada"
    )
    
    change_vehicle_status(
        vehicle=maintenance.vehicle,
        status_name=resulting_status,
        user=user,
        reason=reason or "Cancelamento de manutenção"
    )
    
    return maintenance


@transaction.atomic
def assign_driver_to_vehicle(
    *,
    vehicle: Vehicle,
    driver: Driver,
    user,
    notes: str = "",
    sei_number: str = "",
    custody_started_on=None,
    custody_ended_on=None,
):
    from django.utils import timezone
    from .sector_scope import validate_vehicle_scope

    validate_vehicle_scope(user, vehicle)

    sei_number = (sei_number or "").strip()
    ensure_vehicle_active(vehicle)

    if sei_number and not custody_started_on:
        raise ValueError(
            "A data de início da vigência do SEI é obrigatória quando o SEI é informado."
        )

    if custody_ended_on and not custody_started_on:
        raise ValueError(
            "A data de início da vigência do SEI é obrigatória quando a data final é informada."
        )

    if custody_started_on and custody_ended_on and custody_ended_on < custody_started_on:
        raise ValueError(
            "A data final da vigência do SEI não pode ser anterior à data inicial."
        )

    open_custody = VehicleCustody.objects.select_for_update().filter(vehicle=vehicle, ended_on__isnull=True).first()
    current_assignment = vehicle.driver_assignments.select_for_update().filter(is_active=True).first()

    if open_custody:
        if current_assignment and current_assignment.driver_id == driver.id:
            return current_assignment
        raise ValueError("O veículo está acautelado. Use a transferência com data e hora explícitas.")

    if current_assignment and current_assignment.driver_id == driver.id:
        return current_assignment

    old_value = None
    now = timezone.now()

    if current_assignment:
        old_value = {
            "id": str(current_assignment.driver_id),
            "name": current_assignment.driver.name,
        }
        current_assignment.is_active = False
        current_assignment.ends_on = now
        current_assignment.save(
            update_fields=["is_active", "ends_on", "updated_at"]
        )

    new_assignment = VehicleDriverAssignment.objects.create(
        vehicle=vehicle,
        driver=driver,
        starts_on=now,
        is_active=True,
        notes=notes,
        assigned_by=user,
    )

    if sei_number:
        custody = VehicleCustody.objects.create(
            assignment=new_assignment, vehicle=vehicle, sei_number=sei_number,
            started_on=custody_started_on, ended_on=custody_ended_on,
            notes=notes, created_by=user,
        )
        new_assignment.custody = custody
        new_assignment.save(update_fields=["custody", "updated_at"])

    new_value = {"id": str(driver.id), "name": driver.name}

    VehicleHistory.objects.create(
        vehicle=vehicle,
        field="driver",
        old_value=old_value,
        new_value=new_value,
        reason=notes or "Troca de motorista",
        changed_by=user,
    )

    AuditLog.objects.create(
        user=user,
        module="veículos",
        action="VÍNCULO MOTORISTA",
        entity_type="vehicle",
        entity_id=vehicle.id,
        old_values={"driver": old_value["name"] if old_value else None},
        new_values={"driver": new_value["name"]},
        reason=notes or "Troca de motorista",
    )

    return new_assignment


def _lock_custody_context(custody):
    """Shared lock order: vehicle, custody, active assignment."""
    vehicle = Vehicle.objects.select_for_update().get(pk=custody.vehicle_id)
    custody = VehicleCustody.objects.select_for_update().get(pk=custody.pk, vehicle=vehicle)
    assignment = VehicleDriverAssignment.objects.select_for_update().filter(vehicle=vehicle, is_active=True).first()
    return vehicle, custody, assignment


def get_open_vehicle_custody(vehicle):
    return VehicleCustody.objects.filter(vehicle=vehicle, ended_on__isnull=True).first()


@transaction.atomic
def start_vehicle_custody(*, vehicle, driver, sei_number, started_on, user, notes=""):
    from django.utils import timezone
    sei_number = (sei_number or "").strip()
    if not sei_number or not started_on:
        raise ValueError("SEI e data de início são obrigatórios.")
    if not driver.active:
        raise ValueError("O responsável deve ser um motorista ativo.")
    if started_on > timezone.localdate():
        raise ValueError("A data de início não pode ser futura.")
    vehicle = Vehicle.objects.select_for_update().get(pk=vehicle.pk)
    ensure_vehicle_active(vehicle)
    if VehicleCustody.objects.select_for_update().filter(vehicle=vehicle, ended_on__isnull=True).exists():
        raise ValueError("A viatura já possui acautelamento aberto.")
    current = VehicleDriverAssignment.objects.select_for_update().filter(
        vehicle=vehicle,
        is_active=True,
    ).first()

    if current and current.driver_id != driver.id:
        current.is_active, current.ends_on = False, timezone.now()
        current.save(update_fields=["is_active", "ends_on", "updated_at"])
        current = None

    # N?o reutilizar um assignment que j? pertenceu a uma cust?dia.
    # O v?nculo hist?rico da cust?dia anterior deve permanecer preservado.
    if current and current.custody_id is not None:
        current.is_active, current.ends_on = False, timezone.now()
        current.save(update_fields=["is_active", "ends_on", "updated_at"])
        current = None

    assignment = current or VehicleDriverAssignment.objects.create(
        vehicle=vehicle,
        driver=driver,
        starts_on=timezone.now(),
        is_active=True,
        assigned_by=user,
        notes=notes,
    )
    custody = VehicleCustody.objects.create(assignment=assignment, vehicle=vehicle, sei_number=sei_number, started_on=started_on, notes=notes, created_by=user)
    assignment.custody = custody
    assignment.save(update_fields=["custody", "updated_at"])
    VehicleHistory.objects.create(vehicle=vehicle, field="custody", old_value=None, new_value={"sei": sei_number}, reason=notes, changed_by=user)
    AuditLog.objects.create(user=user, module="acautelamentos", action="INÍCIO", entity_type="vehicle_custody", entity_id=custody.id, old_values=None, new_values={"sei": sei_number, "assignment_id": str(assignment.id)}, reason=notes)
    return custody


@transaction.atomic
def transfer_vehicle_custody(*, custody, new_driver, user, transferred_at, notes=""):
    from django.utils import timezone
    if transferred_at is None or timezone.is_naive(transferred_at):
        raise ValueError("A transferência exige data, hora e fuso horário explícitos.")
    vehicle, custody, current = _lock_custody_context(custody)
    if custody.ended_on or not new_driver.active:
        raise ValueError("Acautelamento encerrado ou responsável inativo.")
    if not current or current.custody_id != custody.id or current.driver_id == new_driver.id:
        raise ValueError("Responsável atual inválido para transferência.")
    if transferred_at > timezone.now() or timezone.localtime(transferred_at).date() < custody.started_on or transferred_at < current.starts_on:
        raise ValueError("Data da transferência inválida.")
    current.is_active, current.ends_on = False, transferred_at
    current.save(update_fields=["is_active", "ends_on", "updated_at"])
    assignment = VehicleDriverAssignment.objects.create(vehicle=vehicle, driver=new_driver, custody=custody,
        starts_on=transferred_at, is_active=True, notes=(notes or "").strip(), assigned_by=user)
    VehicleHistory.objects.create(vehicle=vehicle, field="driver", old_value={"id": str(current.driver_id)}, new_value={"id": str(new_driver.id)}, reason=notes, changed_by=user)
    AuditLog.objects.create(user=user, module="acautelamentos", action="TRANSFERÊNCIA", entity_type="vehicle_custody", entity_id=custody.id, old_values={"assignment_id": str(current.id)}, new_values={"assignment_id": str(assignment.id), "transferred_at": transferred_at.isoformat()}, reason=notes)
    return assignment


@transaction.atomic
def end_vehicle_custody(*, custody, user, ended_on, assignment_ended_at, notes=""):
    from django.utils import timezone
    if assignment_ended_at is None or timezone.is_naive(assignment_ended_at):
        raise ValueError("O encerramento exige data, hora e fuso do responsável.")
    vehicle, custody, current = _lock_custody_context(custody)
    if custody.ended_on or ended_on < custody.started_on or ended_on > timezone.localdate():
        raise ValueError("Data de encerramento inválida.")
    if timezone.localtime(assignment_ended_at).date() != ended_on or assignment_ended_at > timezone.now():
        raise ValueError("Horário de encerramento inválido.")
    if current and current.custody_id not in (None, custody.id):
        raise ValueError("O responsável ativo pertence a outro acautelamento.")
    if current and current.custody_id == custody.id:
        if assignment_ended_at < current.starts_on:
            raise ValueError("O horário antecede a responsabilidade atual.")
        current.is_active, current.ends_on = False, assignment_ended_at
        current.save(update_fields=["is_active", "ends_on", "updated_at"])
    custody.ended_on, custody.ended_by = ended_on, user
    if notes:
        custody.notes = f"{custody.notes}\n[Encerramento] {notes}".strip()
        custody.save(update_fields=["ended_on", "ended_by", "notes", "updated_at"])
    else:
        custody.save(update_fields=["ended_on", "ended_by", "updated_at"])
    VehicleHistory.objects.create(vehicle=vehicle, field="custody", old_value={"ended_on": None}, new_value={"ended_on": ended_on.isoformat()}, reason=notes, changed_by=user)
    AuditLog.objects.create(user=user, module="acautelamentos", action="ENCERRAMENTO", entity_type="vehicle_custody", entity_id=custody.id, old_values={"ended_on": None}, new_values={"ended_on": ended_on.isoformat()}, reason=notes)
    return custody


@transaction.atomic
def unassign_driver_from_vehicle(*, vehicle: Vehicle, user, notes: str = ""):
    from django.utils import timezone
    vehicle = Vehicle.objects.select_for_update().get(pk=vehicle.pk)
    if VehicleCustody.objects.select_for_update().filter(vehicle=vehicle, ended_on__isnull=True).exists():
        raise ValueError("A viatura está acautelada; transfira ou encerre antes de desvincular.")
    current_assignment = vehicle.driver_assignments.select_for_update().filter(is_active=True).first()
    
    if not current_assignment:
        return None
        
    now = timezone.now()
    old_value = {"id": str(current_assignment.driver_id), "name": current_assignment.driver.name}
    
    current_assignment.is_active = False
    current_assignment.ends_on = now
    current_assignment.save(update_fields=["is_active", "ends_on", "updated_at"])
    
    VehicleHistory.objects.create(
        vehicle=vehicle, 
        field="driver", 
        old_value=old_value, 
        new_value=None, 
        reason=notes or "Remoção de motorista", 
        changed_by=user
    )
    
    AuditLog.objects.create(
        user=user, 
        module="veículos", 
        action="DESVÍNCULO MOTORISTA", 
        entity_type="vehicle", 
        entity_id=vehicle.id, 
        old_values={"driver": old_value["name"]}, 
        new_values={"driver": None}, 
        reason=notes or "Remoção de motorista"
    )
    
    return current_assignment


@transaction.atomic
def change_vehicle_plate(*, vehicle: Vehicle, plate: str, kind: str, user, reason: str = ""):
    from django.utils import timezone
    from .models import VehiclePlate
    import re
    
    # Normalização
    normalized_plate = re.sub(r'[^A-Za-z0-9]', '', plate).upper()
    
    current_active = vehicle.plate_history.filter(kind=kind, ends_on__isnull=True).first()
    
    if current_active and current_active.plate == normalized_plate:
        return current_active
        
    now = timezone.now()
    old_value = None
    
    if current_active:
        old_value = current_active.plate
        current_active.ends_on = now
        current_active.save(update_fields=["ends_on", "updated_at"])
        
    new_plate = VehiclePlate.objects.create(
        vehicle=vehicle,
        plate=normalized_plate,
        kind=kind,
        starts_on=now,
        reason=reason,
        changed_by=user
    )
    
    field_name = "current_plate" if kind == VehiclePlate.CURRENT else "reserved_plate"
        
    VehicleHistory.objects.create(
        vehicle=vehicle,
        field=field_name,
        old_value=old_value,
        new_value=normalized_plate,
        reason=reason or f"Troca de placa {kind}",
        changed_by=user
    )
    
    AuditLog.objects.create(
        user=user,
        module="veículos",
        action="TROCA DE PLACA",
        entity_type="vehicle",
        entity_id=vehicle.id,
        old_values={field_name: old_value},
        new_values={field_name: normalized_plate},
        reason=reason or f"Troca de placa {kind}"
    )
    
    return new_plate

@transaction.atomic
def record_vehicle_mileage(*, vehicle: Vehicle, mileage: int, user, origin: str = "MANUAL", notes: str = "", is_correction: bool = False, external_id: str = ""):
    from .models import VehicleMileage
    from .sector_scope import validate_vehicle_scope
    validate_vehicle_scope(user, vehicle)
    from .models import AuditLog
    
    if mileage is None or int(mileage) < 0:
        raise ValueError("A quilometragem não pode ser nula ou negativa.")
        
    latest_mileage_record = vehicle.mileage_history.first()
    current_mileage = latest_mileage_record.mileage if latest_mileage_record else 0
    
    if int(mileage) < current_mileage and not is_correction:
        raise ValueError(f"Quilometragem inválida. O valor informado ({mileage}) é menor que a última quilometragem registrada ({current_mileage}). Marque como correção se for o caso.")
        
    mileage_record = VehicleMileage.objects.create(
        vehicle=vehicle,
        mileage=int(mileage),
        origin=origin,
        recorded_by=user,
        notes=notes,
        is_correction=is_correction,
        external_id=external_id
    )

    if vehicle.revision_reference_km is None:
        vehicle.revision_reference_km = int(mileage)
        vehicle.revision_reference_at = mileage_record.date
        vehicle.revision_reference_source = f"{origin}:{mileage_record.id}"
        vehicle.save(update_fields=[
            "revision_reference_km",
            "revision_reference_at",
            "revision_reference_source",
            "updated_at",
        ])
    
    if origin == VehicleMileage.MANUAL:
        AuditLog.objects.create(
            user=user,
            module="veículos",
            action="REGISTRO DE QUILOMETRAGEM" if not is_correction else "CORREÇÃO DE QUILOMETRAGEM",
            entity_type="vehicle",
            entity_id=vehicle.id,
            old_values={"mileage": current_mileage},
            new_values={"mileage": int(mileage)},
            reason=notes
        )
        
    return vehicle

@transaction.atomic
def record_vehicle_inspection(*, vehicle: Vehicle, type, status, user, inspector_name: str = "", mileage: int = None, notes: str = "", date=None):
    from .models import VehicleInspection, AuditLog
    from .sector_scope import validate_vehicle_scope
    validate_vehicle_scope(user, vehicle)
    from django.utils import timezone
    
    ensure_vehicle_active(vehicle)
    if not date:
        date = timezone.now()
        
    inspection = VehicleInspection.objects.create(
        vehicle=vehicle,
        date=date,
        type=type,
        status=status,
        inspector_name=inspector_name,
        mileage=mileage,
        notes=notes,
        created_by=user
    )
    
    if mileage is not None:
        try:
            record_vehicle_mileage(vehicle=vehicle, mileage=mileage, user=user, notes=f"Vistoria ID {inspection.id}")
        except ValueError as e:
            raise ValueError(f"Erro ao registrar quilometragem da vistoria: {str(e)}")
            
    AuditLog.objects.create(
        user=user,
        module="veículos",
        action="REGISTRO DE VISTORIA",
        entity_type="vehicle_inspection",
        entity_id=inspection.id,
        old_values=None,
        new_values={"status": status.name, "type": type.name},
        reason=notes
    )
    
    return inspection

@transaction.atomic
def create_vehicle_fine(*, vehicle: Vehicle, auto_number: str, agency: str, status, date, user, process_number: str = "", amount=None, due_date=None, notes: str = ""):
    from .models import VehicleFine, AuditLog, SEIProcessStatus
    from .sector_scope import validate_vehicle_scope
    validate_vehicle_scope(user, vehicle)
    
    ensure_vehicle_active(vehicle)
    fine = VehicleFine.objects.create(
        vehicle=vehicle,
        auto_number=auto_number,
        agency=agency,
        status=status,
        date=date,
        amount=amount,
        due_date=due_date,
        notes=notes,
        created_by=user
    )
    
    AuditLog.objects.create(
        user=user,
        module="veículos",
        action="CADASTRO DE MULTA",
        entity_type="vehicle_fine",
        entity_id=fine.id,
        old_values=None,
        new_values={"auto_number": auto_number, "status": status.name},
        reason=notes
    )

    if process_number:
        aberto, _ = SEIProcessStatus.objects.get_or_create(name="Aberto", defaults={"active": True})
        try:
            process = create_sei_process(
                sei_number=process_number,
                status=aberto,
                user=user,
                title=f"Processo de Multa {auto_number}"
            )
        except ValueError:
            from .models import SEIProcess
            process = SEIProcess.objects.get(sei_number=process_number)
            
        link_sei_process(process=process, obj=fine, user=user)
    
    return fine

@transaction.atomic
def update_vehicle_fine(*, fine, user, **kwargs):
    from .models import VehicleFine, AuditLog
    
    old_values = {}
    new_values = {}
    
    fields_to_update = ["auto_number", "agency", "status", "date", "amount", "due_date", "notes"]
    
    for field in fields_to_update:
        if field in kwargs:
            old_val = getattr(fine, field)
            new_val = kwargs[field]
            
            if old_val != new_val:
                if field == "status":
                    old_values[field] = old_val.name if old_val else None
                    new_values[field] = new_val.name if new_val else None
                else:
                    old_values[field] = str(old_val) if old_val is not None else None
                    new_values[field] = str(new_val) if new_val is not None else None
                
                setattr(fine, field, new_val)
                
    if new_values:
        fine.save(update_fields=list(new_values.keys()) + ["updated_at"])
        
        AuditLog.objects.create(
            user=user,
            module="veículos",
            action="ALTERAÇÃO DE MULTA",
            entity_type="vehicle_fine",
            entity_id=fine.id,
            old_values=old_values,
            new_values=new_values,
            reason=kwargs.get("notes", "Atualização de dados")
        )
        
    return fine

@transaction.atomic
def create_sei_process(*, sei_number: str, status, user, title: str = "", category: str = "", opening_date=None, notes: str = ""):
    from .models import SEIProcess, AuditLog
    
    if SEIProcess.objects.filter(sei_number=sei_number).exists():
        raise ValueError(f"O processo SEI {sei_number} já existe.")
        
    process = SEIProcess.objects.create(
        sei_number=sei_number,
        title=title,
        status=status,
        category=category,
        opening_date=opening_date,
        notes=notes,
        created_by=user
    )
    
    AuditLog.objects.create(
        user=user,
        module="processos",
        action="CADASTRO DE PROCESSO SEI",
        entity_type="sei_process",
        entity_id=process.id,
        old_values=None,
        new_values={"sei_number": sei_number, "status": status.name},
        reason=notes
    )
    
    return process

@transaction.atomic
def update_sei_process(*, process, user, **kwargs):
    from .models import SEIProcess, AuditLog
    from django.utils import timezone
    
    old_values = {}
    new_values = {}
    
    fields_to_update = ["title", "status", "category", "opening_date", "closing_date", "notes"]
    
    for field in fields_to_update:
        if field in kwargs:
            old_val = getattr(process, field)
            new_val = kwargs[field]
            
            if old_val != new_val:
                if field == "status":
                    old_values[field] = old_val.name if old_val else None
                    new_values[field] = new_val.name if new_val else None
                    
                    if new_val.name in ["Encerrado", "Cancelado", "Arquivado"] and not process.closing_date:
                        process.closing_date = timezone.now().date()
                        new_values["closing_date"] = str(process.closing_date)
                else:
                    old_values[field] = str(old_val) if old_val is not None else None
                    new_values[field] = str(new_val) if new_val is not None else None
                
                setattr(process, field, new_val)
                
    if new_values:
        process.save(update_fields=list(new_values.keys()) + ["updated_at"])
        
        AuditLog.objects.create(
            user=user,
            module="processos",
            action="ALTERAÇÃO DE PROCESSO SEI",
            entity_type="sei_process",
            entity_id=process.id,
            old_values=old_values,
            new_values=new_values,
            reason=kwargs.get("notes", "Atualização de dados")
        )
        
    return process

@transaction.atomic
def link_sei_process(*, process, obj, user):
    from .models import SEIProcessRelation, AuditLog
    from django.contrib.contenttypes.models import ContentType
    
    ct = ContentType.objects.get_for_model(obj)
    relation, created = SEIProcessRelation.objects.get_or_create(
        process=process,
        content_type=ct,
        object_id=obj.id,
        defaults={'created_by': user}
    )
    
    if created:
        AuditLog.objects.create(
            user=user,
            module="processos",
            action="VINCULAÇÃO DE PROCESSO SEI",
            entity_type="sei_process",
            entity_id=process.id,
            old_values=None,
            new_values={"content_type": ct.model, "object_id": str(obj.id)},
            reason=f"Processo vinculado a {ct.model} ID {obj.id}"
        )
        
    return relation


@transaction.atomic
def create_document(*, title: str, document_type_id: str, document_date, file_obj, user, notes: str = ""):
    from .models import Document, DocumentVersion, DocumentStatus, DocumentType, AuditLog
    from django.conf import settings
    import os
    import mimetypes
    
    file_size = file_obj.size
    max_size = getattr(settings, 'DOCUMENT_MAX_UPLOAD_SIZE', 10 * 1024 * 1024)
    if file_size > max_size:
        raise ValueError(f"O tamanho do arquivo excede o limite permitido ({max_size} bytes).")
        
    original_filename = file_obj.name
    ext = original_filename.split('.')[-1].lower() if '.' in original_filename else ''
    allowed_exts = getattr(settings, 'DOCUMENT_ALLOWED_EXTENSIONS', ['pdf', 'png', 'jpg', 'jpeg'])
    if ext not in allowed_exts:
        raise ValueError(f"Extensão de arquivo não permitida. Permitidos: {', '.join(allowed_exts)}")
        
    mime_type, _ = mimetypes.guess_type(original_filename)
    if not mime_type:
        mime_type = "application/octet-stream"

    status_ativo, _ = DocumentStatus.objects.get_or_create(name="Ativo", defaults={"active": True})
    doc_type = DocumentType.objects.get(id=document_type_id)

    document = Document.objects.create(
        title=title,
        document_type=doc_type,
        status=status_ativo,
        document_date=document_date,
        notes=notes,
        created_by=user
    )
    
    version = DocumentVersion.objects.create(
        document=document,
        file=file_obj,
        original_filename=original_filename,
        file_extension=ext,
        mime_type=mime_type,
        file_size=file_size,
        uploaded_by=user
    )
    
    AuditLog.objects.create(
        user=user,
        module="documentos",
        action="CADASTRO DE DOCUMENTO",
        entity_type="document",
        entity_id=document.id,
        old_values=None,
        new_values={
            "title": title, 
            "type": doc_type.name,
            "filename": original_filename,
            "size": file_size
        },
        reason=notes
    )
    
    return document


@transaction.atomic
def add_document_version(*, document, file_obj, user, notes: str = ""):
    from .models import DocumentVersion, AuditLog
    from django.conf import settings
    import mimetypes
    
    file_size = file_obj.size
    max_size = getattr(settings, 'DOCUMENT_MAX_UPLOAD_SIZE', 10 * 1024 * 1024)
    if file_size > max_size:
        raise ValueError(f"O tamanho do arquivo excede o limite permitido ({max_size} bytes).")
        
    original_filename = file_obj.name
    ext = original_filename.split('.')[-1].lower() if '.' in original_filename else ''
    allowed_exts = getattr(settings, 'DOCUMENT_ALLOWED_EXTENSIONS', ['pdf', 'png', 'jpg', 'jpeg'])
    if ext not in allowed_exts:
        raise ValueError(f"Extensão de arquivo não permitida. Permitidos: {', '.join(allowed_exts)}")
        
    mime_type, _ = mimetypes.guess_type(original_filename)
    if not mime_type:
        mime_type = "application/octet-stream"

    version = DocumentVersion.objects.create(
        document=document,
        file=file_obj,
        original_filename=original_filename,
        file_extension=ext,
        mime_type=mime_type,
        file_size=file_size,
        uploaded_by=user
    )
    
    if notes:
        document.notes = notes
        document.save(update_fields=['notes', 'updated_at'])
    
    AuditLog.objects.create(
        user=user,
        module="documentos",
        action="NOVA VERSÃO DE DOCUMENTO",
        entity_type="document",
        entity_id=document.id,
        old_values=None,
        new_values={
            "filename": original_filename,
            "size": file_size,
            "version_id": str(version.id)
        },
        reason=notes
    )
    
    return version


@transaction.atomic
def archive_document(*, document, user, reason: str = ""):
    from .models import DocumentStatus, AuditLog
    
    if document.status.name == "Arquivado":
        raise ValueError("Documento já está arquivado.")
        
    arquivado, _ = DocumentStatus.objects.get_or_create(name="Arquivado", defaults={"active": True})
    
    old_status = document.status.name
    document.status = arquivado
    document.save(update_fields=["status", "updated_at"])
    
    AuditLog.objects.create(
        user=user,
        module="documentos",
        action="ARQUIVAMENTO DE DOCUMENTO",
        entity_type="document",
        entity_id=document.id,
        old_values={"status": old_status},
        new_values={"status": "Arquivado"},
        reason=reason
    )
    
    return document


@transaction.atomic
def link_document(*, document, obj, user):
    from .models import DocumentRelation, AuditLog
    from django.contrib.contenttypes.models import ContentType
    
    ct = ContentType.objects.get_for_model(obj)
    relation, created = DocumentRelation.objects.get_or_create(
        document=document,
        content_type=ct,
        object_id=obj.id,
        defaults={'created_by': user}
    )
    
    if created:
        AuditLog.objects.create(
            user=user,
            module="documentos",
            action="VINCULAÇÃO DE DOCUMENTO",
            entity_type="document",
            entity_id=document.id,
            old_values=None,
            new_values={"content_type": ct.model, "object_id": str(obj.id)},
            reason=f"Documento vinculado a {ct.model} ID {obj.id}"
        )
        
    return relation


def get_dashboard_metrics(filters: dict) -> dict:
    from .models import (
        Vehicle, Contract, Maintenance, VehicleInspection, 
        VehicleFine, SEIProcess, Document
    )
    from django.db.models import Count, Q
    from django.utils import timezone
    
    # 1. Base QuerySet for Vehicles
    v_qs = Vehicle.objects.filter(active=True)
    
    unit = filters.get("unit")
    base = filters.get("base")
    renter = filters.get("renter")
    status = filters.get("status")
    vehicle_ids = filters.get("vehicle__in")
    
    if vehicle_ids is not None: v_qs = v_qs.filter(id__in=vehicle_ids)
    if unit: v_qs = v_qs.filter(unit_id=unit)
    if base: v_qs = v_qs.filter(base_id=base)
    if renter: v_qs = v_qs.filter(renter_id=renter)
    if status: v_qs = v_qs.filter(status_id=status)
    
    # Aggregate Vehicle Counts by Status Name
    # We use list comprehension and group by to avoid N+1
    v_counts = v_qs.values('status__name').annotate(count=Count('id'))
    fleet_metrics = {
        "total": v_qs.count(),
        "by_status": {item['status__name']: item['count'] for item in v_counts}
    }
    
    # We need an array of vehicle IDs to filter related entities that depend on Vehicle
    vehicle_ids = v_qs.values_list('id', flat=True) if filters else None
    
    # 2. Contracts
    # Contracts are directly related to Vehicles via `contract` field. 
    # But wait, Contracts are standalone, multiple vehicles can point to one contract.
    # We filter contracts if they are attached to the filtered vehicles.
    c_qs = Contract.objects.all()
    if vehicle_ids is not None:
        c_qs = c_qs.filter(vehicles__in=vehicle_ids).distinct()
        
    c_counts = c_qs.values('administrative_status').annotate(count=Count('id'))
    contract_metrics = {
        "total": c_qs.count(),
        "by_status": {item['administrative_status']: item['count'] for item in c_counts}
    }
    
    # 3. Maintenances
    m_qs = Maintenance.objects.all()
    if vehicle_ids is not None:
        m_qs = m_qs.filter(vehicle_id__in=vehicle_ids)
        
    m_counts = m_qs.values('status__name').annotate(count=Count('id'))
    maintenance_metrics = {
        "total": m_qs.count(),
        "by_status": {item['status__name']: item['count'] for item in m_counts}
    }
    
    # 4. Inspections
    i_qs = VehicleInspection.objects.all()
    if vehicle_ids is not None:
        i_qs = i_qs.filter(vehicle_id__in=vehicle_ids)
        
    i_counts = i_qs.values('status__name').annotate(count=Count('id'))
    inspection_metrics = {
        "total": i_qs.count(),
        "by_status": {item['status__name']: item['count'] for item in i_counts}
    }
    
    # 5. Fines
    f_qs = VehicleFine.objects.all()
    if vehicle_ids is not None:
        f_qs = f_qs.filter(vehicle_id__in=vehicle_ids)
        
    f_counts = f_qs.values('status__name').annotate(count=Count('id'))
    fine_metrics = {
        "total": f_qs.count(),
        "by_status": {item['status__name']: item['count'] for item in f_counts}
    }
    
    # 6. Processos SEI e acautelamentos legados.
    # Os veículos importados guardam seu SEI/acautelamento em ``custody_info``.
    # Enquanto esses registros não forem convertidos em SEIProcess, eles também
    # precisam integrar o indicador operacional.
    sei_counts = SEIProcess.objects.values('status__name').annotate(count=Count('id'))
    legacy_custody_count = v_qs.exclude(custody_info__isnull=True).exclude(custody_info__exact='').count()
    sei_metrics = {
        "total": SEIProcess.objects.count() + legacy_custody_count,
        "by_status": {
            **{item['status__name']: item['count'] for item in sei_counts},
            "Acautelamentos legados": legacy_custody_count,
        }
    }

    doc_counts = Document.objects.values('status__name').annotate(count=Count('id'))
    doc_metrics = {
        "total": Document.objects.count(),
        "by_status": {item['status__name']: item['count'] for item in doc_counts}
    }

    return {
        "fleet": fleet_metrics,
        "contracts": contract_metrics,
        "maintenance": maintenance_metrics,
        "inspections": inspection_metrics,
        "fines": fine_metrics,
        "sei_processes": sei_metrics,
        "documents": doc_metrics,
    }


def get_operational_alerts(filters: dict) -> dict:
    from .models import (
        Contract, Maintenance, VehicleInspection, VehicleFine, SEIProcess, SystemParameter
    )
    from django.utils import timezone
    from datetime import timedelta
    
    today = timezone.now().date()
    vehicle_ids = filters.get("vehicle__in")
    
    # Fetch threshold from DB
    try:
        warning_days = int(SystemParameter.objects.get(key="CONTRACT_EXPIRY_WARNING_DAYS").value)
    except Exception:
        warning_days = 30
        
    warning_date = today + timedelta(days=warning_days)
    
    # 1. Contracts expiring soon (status Vigente, ends_on <= warning_date)
    expiring_contracts = Contract.objects.filter(
        administrative_status__iexact="VIGENTE",
        ends_on__lte=warning_date,
        ends_on__gte=today
    )
    if vehicle_ids is not None:
        expiring_contracts = expiring_contracts.filter(vehicles__in=vehicle_ids).distinct()
    expiring_contracts = expiring_contracts.values("id", "number", "ends_on")
    
    expired_contracts = Contract.objects.filter(
        administrative_status__iexact="VIGENTE",
        ends_on__lt=today
    )
    if vehicle_ids is not None:
        expired_contracts = expired_contracts.filter(vehicles__in=vehicle_ids).distinct()
    expired_contracts = expired_contracts.values("id", "number", "ends_on")
    
    # 2. Open Maintenances
    open_maintenances = Maintenance.objects.filter(
        status__name__in=["Aberta", "Em andamento"]
    )
    if vehicle_ids is not None:
        open_maintenances = open_maintenances.filter(vehicle_id__in=vehicle_ids).select_related('vehicle').values("id", "vehicle__plate_history__plate", "status__name", "entered_at")
    
    # 3. Pending Fines
    from django.db.models import Prefetch
    from .models import VehicleDriverAssignment

    pending_fines_qs = VehicleFine.objects.filter(
        status__name__in=["Pendente", "Em análise", "Em recurso"]
    )
    if vehicle_ids is not None:
        pending_fines_qs = pending_fines_qs.filter(vehicle_id__in=vehicle_ids).select_related('vehicle', 'status').prefetch_related(
        Prefetch(
            'vehicle__driver_assignments',
            queryset=VehicleDriverAssignment.objects.filter(is_active=True).select_related('driver'),
            to_attr='active_driver_assignments',
        ),
        'vehicle__plate_history',
    )
    pending_fines = []
    for fine in pending_fines_qs:
        driver_assignments = getattr(fine.vehicle, 'active_driver_assignments', [])
        driver_name = driver_assignments[0].driver.name if driver_assignments else None
        plate = next(
            (p.plate for p in fine.vehicle.plate_history.all()
             if p.kind == 'CURRENT' and p.ends_on is None),
            None,
        )
        pending_fines.append({
            "id": fine.id,
            "vehicle__plate_history__plate": plate,
            "status__name": fine.status.name,
            "date": fine.date,
            "driver__name": driver_name,
        })
    
    # 4. Open SEI Processes
    open_sei = SEIProcess.objects.filter(
        status__name__in=["Aberto", "Em andamento"]
    ).values("id", "sei_number", "status__name", "opening_date")
    
    # 5. Pending Inspections (Reprovadas ou Com ressalvas)
    pending_inspections = VehicleInspection.objects.filter(
        status__name__in=["Reprovada", "Com ressalvas"]
    )
    if vehicle_ids is not None:
        pending_inspections = pending_inspections.filter(vehicle_id__in=vehicle_ids).select_related('vehicle').values("id", "vehicle__plate_history__plate", "status__name", "date")

    # 6. Revisoes preventivas
    # Regra oficial WW Trans:
    # - intervalo de 10.000 km;
    # - alerta nos ultimos 3.000 km;
    # - somente Revisao + Concluida + KM informado estabelece o ciclo.
    from .models import Vehicle

    revisoes_vencidas = []

    qs_vehicles = Vehicle.objects.prefetch_related('plate_history')
    if vehicle_ids is not None:
        qs_vehicles = qs_vehicles.filter(id__in=vehicle_ids)

    for v in qs_vehicles:
        revision = get_vehicle_revision_status(vehicle=v)

        if revision['status'] not in ('DEVIDA', 'PROXIMA'):
            continue

        plate = "-"
        for p in v.plate_history.all():
            if not p.ends_on and p.kind == 'CURRENT':
                plate = p.plate
                break

        revisoes_vencidas.append({
            'vehicle_id': v.id,
            'plate': plate,
            'km_atual': revision['current_km'],
            'km_prox_revisao': revision['next_revision_km'],
            'km_faltando': revision['km_remaining'],
            'status': revision['status'],
            'last_revision_km': revision['last_revision_km'],
            'ultrapassado': max(0, -revision['km_remaining']),
        })

    # Revisoes devidas primeiro; depois as proximas mais urgentes.
    revisoes_vencidas.sort(
        key=lambda x: (
            0 if x['status'] == 'DEVIDA' else 1,
            x['km_faltando'] if x['km_faltando'] is not None else 999999,
        )
    )

    from .models import Driver
    expired_cnh = Driver.objects.filter(
        cnh_expiration__lt=today
    ).values("id", "name", "cnh_number", "cnh_expiration")

    return {
        "expiring_contracts": list(expiring_contracts),
        "expired_contracts": list(expired_contracts),
        "open_maintenances": list(open_maintenances),
        "pending_fines": list(pending_fines),
        "open_sei": list(open_sei),
        "pending_inspections": list(pending_inspections),
        "revisoes_vencidas": revisoes_vencidas,
        "expired_cnh": list(expired_cnh),
    }


@transaction.atomic
def set_vehicle_active(*, vehicle: Vehicle, active: bool, user, reason: str = ""):
    """Applies the manual operational visibility flag without touching status."""
    from .models import VehicleExitOrder

    if vehicle.active == active:
        return vehicle
    if not active:
        pending_order = VehicleExitOrder.objects.filter(
            vehicle=vehicle, state=VehicleExitOrder.State.PENDING
        ).exists()
        open_maintenance = Maintenance.objects.filter(
            vehicle=vehicle, exited_at__isnull=True,
            status__name__in=["Aberta", "Em andamento"],
        ).exists()
        if pending_order or open_maintenance:
            pending = []
            if pending_order:
                pending.append("ordem de saída pendente")
            if open_maintenance:
                pending.append("manutenção aberta/em andamento")
            raise ValueError("Não é possível inativar: " + " e ".join(pending) + ".")

    old_active = vehicle.active
    vehicle.active = active
    vehicle.save(update_fields=["active", "updated_at"])
    VehicleHistory.objects.create(
        vehicle=vehicle, field="active", old_value={"active": old_active},
        new_value={"active": active}, reason=reason, changed_by=user,
    )
    AuditLog.objects.create(
        user=user, module="veículos", action="ATIVAÇÃO DE VEÍCULO" if active else "INATIVAÇÃO DE VEÍCULO",
        entity_type="vehicle", entity_id=vehicle.id,
        old_values={"active": old_active}, new_values={"active": active}, reason=reason,
    )
    return vehicle


def ensure_vehicle_active(vehicle: Vehicle):
    if not vehicle.active:
        raise ValueError("A viatura está inativa e não aceita novos lançamentos.")


@transaction.atomic
def change_vehicle_position(*, vehicle: Vehicle, sector, active: bool, user, reason: str):
    """Altera a alocação setorial e a situação operacional da viatura em uma única operação auditada."""
    from .models import AuditLog, VehicleHistory

    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValueError("Informe o motivo da alteração.")
    if sector is None or sector.slug not in {"adm", "lei-seca"}:
        raise ValueError("Setor de destino inválido.")

    old_sector = vehicle.sector
    old_active = vehicle.active
    old_sector_id = vehicle.sector_id
    new_sector_id = sector.id
    active_changed = old_active != active

    if old_sector_id == new_sector_id and not active_changed:
        raise ValueError("Nenhuma alteração foi informada.")

    vehicle.sector = sector
    vehicle.active = active
    vehicle.save(update_fields=["sector", "active", "updated_at"])

    if old_sector_id != new_sector_id:
        VehicleHistory.objects.create(
            vehicle=vehicle,
            field="sector",
            old_value={"id": str(old_sector.id), "name": old_sector.name, "slug": old_sector.slug} if old_sector else None,
            new_value={"id": str(sector.id), "name": sector.name, "slug": sector.slug},
            reason=reason,
            changed_by=user,
        )

    if active_changed:
        VehicleHistory.objects.create(
            vehicle=vehicle,
            field="active",
            old_value={"active": old_active},
            new_value={"active": active},
            reason=reason,
            changed_by=user,
        )

    AuditLog.objects.create(
        user=user,
        module="veículos",
        action="MOVIMENTAÇÃO DE VIATURA",
        entity_type="vehicle",
        entity_id=vehicle.id,
        old_values={
            "sector": {"id": str(old_sector.id), "name": old_sector.name, "slug": old_sector.slug} if old_sector else None,
            "active": old_active,
        },
        new_values={
            "sector": {"id": str(sector.id), "name": sector.name, "slug": sector.slug},
            "active": active,
        },
        reason=reason,
    )
    return vehicle
