import logging
from django.db import transaction
from django.utils import timezone
from apps.fleet.models import BDT, Vehicle, Driver
from uuid import UUID

logger = logging.getLogger(__name__)

class BDTSyncWorker:
    """
    Processador oficial de sincronização de BDTs.
    Pode ser chamado pela API (BDTSyncAPIView) ou pelo Worker Local (horus_sync.py).
    Recebe uma lista de dicionários com chaves do Horus e atualiza o banco local via bulk operations.
    """
    def __init__(self, rows):
        self.rows = rows

    def _safe_uuid(self, val):
        if not val:
            return None
        if isinstance(val, UUID):
            return val
        try:
            return UUID(str(val))
        except (ValueError, TypeError, AttributeError):
            return None

    def run(self, managements_map=None):
        if managements_map is None:
            managements_map = {}
            
        resumo = {
            "processados": len(self.rows),
            "criados": 0,
            "atualizados": 0,
            "falhas": 0,
            "erros": []
        }
        
        if not self.rows:
            return resumo

        # 1. Normalizando todos os IDs antes das buscas e indexações
        fleet_ids = set()
        user_ids = set()
        external_ids = set()
        valid_rows = []

        for row in self.rows:
            try:
                ext_id = self._safe_uuid(row.get('id'))
                if not ext_id:
                    raise ValueError(f"ID externo inválido ou ausente: {row.get('id')}")

                fleet_id = self._safe_uuid(row.get('fleet_id'))
                if fleet_id:
                    fleet_ids.add(fleet_id)

                user_id = self._safe_uuid(row.get('user_id'))
                if user_id:
                    user_ids.add(user_id)

                external_ids.add(ext_id)
                
                # Armazena as versões UUID na row para evitar parse duplo e miss mappings
                row['_ext_id_uuid'] = ext_id
                row['_fleet_id_uuid'] = fleet_id
                row['_user_id_uuid'] = user_id
                
                valid_rows.append(row)
            except Exception as e:
                resumo["falhas"] += 1
                resumo["erros"].append({
                    "external_id": str(row.get('id', 'Desconhecido')),
                    "tipo": type(e).__name__,
                    "mensagem": str(e)
                })

        # 2. Buscas Locais Unificadas usando as chaves normalizadas
        vehicles_map = {v.horus_fleet_id: v for v in Vehicle.objects.filter(horus_fleet_id__in=list(fleet_ids))}
        drivers_map = {d.horus_user_id: d for d in Driver.objects.filter(horus_user_id__in=list(user_ids))}
        existing_bdts = BDT.objects.filter(external_id__in=list(external_ids)).in_bulk(field_name='external_id')
        
        to_create = []
        to_update = []
        
        # 3. Instanciação Protegida
        for row in valid_rows:
            try:
                ext_id = row['_ext_id_uuid']
                fleet_id = row['_fleet_id_uuid']
                user_id = row['_user_id_uuid']
                m_id = row.get('management_id')
                
                # Regra estrita de fallback do watermark temporal
                src_updated_at = row.get('updated_at') or row.get('created_at')
                
                inst = BDT(
                    external_id=ext_id,
                    vehicle=vehicles_map.get(fleet_id),
                    driver=drivers_map.get(user_id),
                    horus_management_id=m_id,
                    horus_adm_id=self._safe_uuid(row.get('adm_id')),
                    horus_service_id=self._safe_uuid(row.get('service_id')),
                    horus_sector_id=row.get('sector_id'),
                    started_at=row.get('started_at'),
                    ended_at=row.get('ended_at'),
                    started_km=row.get('started_km'),
                    ended_km=row.get('ended_km'),
                    latitude_match=row.get('latitude_match'),
                    longitude_match=row.get('longitude_match'),
                    latitude_retreat=row.get('latitude_retreat'),
                    longitude_retreat=row.get('longitude_retreat'),
                    note=row.get('note') or "",
                    horus_active=row.get('active'),
                    management_name=managements_map.get(m_id, ""),
                    source_created_at=row.get('created_at'),
                    source_updated_at=src_updated_at,
                    last_synced_at=timezone.now()
                )
                
                if ext_id in existing_bdts:
                    inst.pk = existing_bdts[ext_id].pk
                    to_update.append(inst)
                else:
                    to_create.append(inst)
            except Exception as e:
                resumo["falhas"] += 1
                resumo["erros"].append({
                    "external_id": str(row.get('id', 'Desconhecido')),
                    "tipo": type(e).__name__,
                    "mensagem": str(e)
                })

        # 4. Escrita Transacional no Banco
        with transaction.atomic():
            if to_create:
                BDT.objects.bulk_create(to_create, batch_size=1000)
                resumo["criados"] += len(to_create)
                
            if to_update:
                update_fields = [
                    'vehicle', 'driver', 'horus_management_id', 'horus_adm_id', 'horus_service_id', 'horus_sector_id',
                    'started_at', 'ended_at', 'started_km', 'ended_km', 'latitude_match', 'longitude_match',
                    'latitude_retreat', 'longitude_retreat', 'note', 'horus_active', 'management_name',
                    'source_created_at', 'source_updated_at', 'last_synced_at'
                ]
                BDT.objects.bulk_update(to_update, fields=update_fields, batch_size=1000)
                resumo["atualizados"] += len(to_update)
            
        return resumo
