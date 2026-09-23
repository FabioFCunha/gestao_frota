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

    current_mileage = (
        VehicleMileage.objects
        .filter(vehicle=vehicle)
        .order_by("-date", "-created_at")
        .values_list("mileage", flat=True)
        .first()
    ) or 0

    active_revision = None

    if revision_type:
        active_revision = (
            Maintenance.objects
            .filter(
                vehicle=vehicle,
                type=revision_type,
                exited_at__isnull=True,
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
        if not legacy_reference:
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
            }
        last_revision_km = None
        next_revision_km = int(legacy_reference.group(1))
        has_history = False

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


@transaction.atomic
def open_maintenance(*, maintenance: Maintenance, user):
    """Applies the mandatory backend transition caused by opening maintenance."""
    if maintenance.status.name.casefold() != "aberta":
        return maintenance
        
    vehicle = maintenance.vehicle
    
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

    sei_number = (sei_number or "").strip()

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

    current_assignment = vehicle.driver_assignments.filter(is_active=True).first()

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

        VehicleCustody.objects.filter(
            assignment=current_assignment,
            ended_on__isnull=True,
        ).update(
            ended_on=now.date(),
            updated_at=now,
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
        VehicleCustody.objects.create(
            assignment=new_assignment,
            sei_number=sei_number,
            started_on=custody_started_on,
            ended_on=custody_ended_on,
            notes=notes,
        )

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


@transaction.atomic
def unassign_driver_from_vehicle(*, vehicle: Vehicle, user, notes: str = ""):
    from django.utils import timezone
    current_assignment = vehicle.driver_assignments.filter(is_active=True).first()
    
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
    from .models import AuditLog
    
    if mileage is None or int(mileage) < 0:
        raise ValueError("A quilometragem não pode ser nula ou negativa.")
        
    latest_mileage_record = vehicle.mileage_history.first()
    current_mileage = latest_mileage_record.mileage if latest_mileage_record else 0
    
    if int(mileage) < current_mileage and not is_correction:
        raise ValueError(f"Quilometragem inválida. O valor informado ({mileage}) é menor que a última quilometragem registrada ({current_mileage}). Marque como correção se for o caso.")
        
    VehicleMileage.objects.create(
        vehicle=vehicle,
        mileage=int(mileage),
        origin=origin,
        recorded_by=user,
        notes=notes,
        is_correction=is_correction,
        external_id=external_id
    )
    
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
    from django.utils import timezone
    
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
    v_qs = Vehicle.objects.all()
    
    unit = filters.get("unit")
    base = filters.get("base")
    renter = filters.get("renter")
    status = filters.get("status")
    
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
    ).values("id", "number", "ends_on")
    
    expired_contracts = Contract.objects.filter(
        administrative_status__iexact="VIGENTE",
        ends_on__lt=today
    ).values("id", "number", "ends_on")
    
    # 2. Open Maintenances
    open_maintenances = Maintenance.objects.filter(
        status__name__in=["Aberta", "Em andamento"]
    ).select_related('vehicle').values("id", "vehicle__plate_history__plate", "status__name", "entered_at")
    
    # 3. Pending Fines
    pending_fines = VehicleFine.objects.filter(
        status__name__in=["Pendente", "Em análise", "Em recurso"]
    ).select_related('vehicle').values("id", "vehicle__plate_history__plate", "status__name", "date")
    
    # 4. Open SEI Processes
    open_sei = SEIProcess.objects.filter(
        status__name__in=["Aberto", "Em andamento"]
    ).values("id", "sei_number", "status__name", "opening_date")
    
    # 5. Pending Inspections (Reprovadas ou Com ressalvas)
    pending_inspections = VehicleInspection.objects.filter(
        status__name__in=["Reprovada", "Com ressalvas"]
    ).select_related('vehicle').values("id", "vehicle__plate_history__plate", "status__name", "date")

    # 6. Revisoes preventivas
    # Regra oficial WW Trans:
    # - intervalo de 10.000 km;
    # - alerta nos ultimos 3.000 km;
    # - somente Revisao + Concluida + KM informado estabelece o ciclo.
    from .models import Vehicle

    revisoes_vencidas = []

    qs_vehicles = Vehicle.objects.prefetch_related('plate_history')

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

    return {
        "expiring_contracts": list(expiring_contracts),
        "expired_contracts": list(expired_contracts),
        "open_maintenances": list(open_maintenances),
        "pending_fines": list(pending_fines),
        "open_sei": list(open_sei),
        "pending_inspections": list(pending_inspections),
        "revisoes_vencidas": revisoes_vencidas
    }
