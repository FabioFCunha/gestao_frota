from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import os

import psycopg
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import (
    BDT,
    Driver,
    Vehicle,
    VehiclePlate,
    VehicleStatus,
)


@dataclass
class SyncStats:
    fleets_read: int = 0
    fleets_created: int = 0
    fleets_updated: int = 0
    drivers_read: int = 0
    drivers_created: int = 0
    drivers_updated: int = 0
    bdts_read: int = 0
    bdts_created: int = 0
    bdts_updated: int = 0
    bdts_skipped: int = 0


class HorusBDTSyncer:
    """
    Sincroniza a frota Lei Seca e seus BDTs do Hórus.

    A origem Hórus é acessada por uma conexão PostgreSQL separada,
    exclusivamente para leitura.
    """

    def __init__(
        self,
        *,
        dry_run: bool = False,
        limit: int | None = None,
    ):
        self.dry_run = dry_run
        self.limit = limit

        self.management_id = int(
            os.getenv("HORUS_LEI_SECA_MANAGEMENT_ID", "49")
        )
        self.lookback_days = int(
            os.getenv("HORUS_BDT_LOOKBACK_DAYS", "90")
        )

        self.stats = SyncStats()

    def _required_env(self, name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(
                f"Variável de ambiente obrigatória não configurada: {name}"
            )
        return value

    def _connect(self):
        conn = psycopg.connect(
            host=self._required_env("HORUS_DB_HOST"),
            port=int(os.getenv("HORUS_DB_PORT", "5432")),
            dbname=self._required_env("HORUS_DB_NAME"),
            user=self._required_env("HORUS_DB_USER"),
            password=self._required_env("HORUS_DB_PASSWORD"),
            connect_timeout=int(
                os.getenv("HORUS_DB_CONNECT_TIMEOUT", "10")
            ),
        )

        conn.read_only = True
        conn.autocommit = False

        return conn

    def _system_user(self):
        email = os.getenv("SYSTEM_CREATOR_EMAIL")

        if not email:
            raise RuntimeError(
                "SYSTEM_CREATOR_EMAIL não configurado."
            )

        User = get_user_model()

        user = User.objects.filter(email__iexact=email).first()

        if not user:
            raise RuntimeError(
                f"Usuário de sistema não encontrado: {email}"
            )

        return user

    def _vehicle_status(self):
        status, _ = VehicleStatus.objects.get_or_create(
            name="Operacional",
            defaults={
                "color": "#16A34A",
            },
        )
        return status

    def _fleet_cutoff(self):
        return timezone.now() - timedelta(days=self.lookback_days)

    def _fetch_bdts(self, conn):
        cutoff = self._fleet_cutoff()

        sql = """
            SELECT
                b.id,
                b.management_id,
                b.fleet_id,
                b.user_id,
                b.adm_id,
                b.started_at,
                b.started_km,
                b.ended_at,
                b.ended_km,
                b.latitude_match,
                b.longitude_match,
                b.latitude_retreat,
                b.longitude_retreat,
                b.note,
                b.active,
                b.created_at,
                b.updated_at,
                b.service_id,
                b.sector_id
            FROM public.bdtds b
            WHERE b.management_id = %s
              AND b.started_at >= %s
            ORDER BY b.started_at, b.id
        """

        params = [self.management_id, cutoff]

        if self.limit:
            sql += " LIMIT %s"
            params.append(self.limit)

        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [item.name for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _fetch_fleets(self, conn, fleet_ids):
        if not fleet_ids:
            return []

        sql = """
            SELECT
                f.id,
                f.management_id,
                f.user_id,
                f.plate,
                f.special_plate,
                f.make_car_id,
                f.model_car_id,
                f.status_vehicle,
                f.created_at,
                f.updated_at
            FROM public.fleets f
            WHERE f.id = ANY(%s)
        """

        with conn.cursor() as cursor:
            cursor.execute(sql, (list(fleet_ids),))
            columns = [item.name for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _fetch_users(self, conn, user_ids):
        if not user_ids:
            return []

        sql = """
            SELECT
                u.id,
                u.first_name,
                u.last_name,
                u.document
            FROM public.users u
            WHERE u.id = ANY(%s)
        """

        with conn.cursor() as cursor:
            cursor.execute(sql, (list(user_ids),))
            columns = [item.name for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _sync_driver(self, row):
        driver, created = Driver.objects.get_or_create(
            horus_user_id=row["id"],
            defaults={
                "name": (f'{row.get("first_name") or ""} ' f'{row.get("last_name") or ""}').strip() or f'Horus {row["id"]}',
            },
        )

        changed = False
        name = (f'{row.get("first_name") or ""} ' f'{row.get("last_name") or ""}').strip()

        if name and driver.name != name:
            driver.name = name
            changed = True

        if row.get("document") and not driver.registration:
            driver.registration = row["document"]
            changed = True

        if changed and not self.dry_run:
            driver.save(update_fields=["name", "registration", "updated_at"])

        if created:
            self.stats.drivers_created += 1
        elif changed:
            self.stats.drivers_updated += 1

        return driver

    def _sync_vehicle(self, row, system_user, vehicle_status):
        vehicle, created = Vehicle.objects.get_or_create(
            horus_fleet_id=row["id"],
            defaults={
                "status": vehicle_status,
                "created_by": system_user,
            },
        )

        changed = False

        if vehicle.status_id != vehicle_status.id:
            vehicle.status = vehicle_status
            changed = True

        if changed and not self.dry_run:
            vehicle.save(update_fields=["status", "updated_at"])

        if created:
            self.stats.fleets_created += 1
        elif changed:
            self.stats.fleets_updated += 1

        plate = row.get("plate") or row.get("special_plate")

        if (
            plate
            and not self.dry_run
            and not VehiclePlate.objects.filter(
                vehicle=vehicle,
                plate=plate,
                kind=VehiclePlate.CURRENT,
                ends_on__isnull=True,
            ).exists()
        ):
            current = VehiclePlate.objects.filter(
                vehicle=vehicle,
                kind=VehiclePlate.CURRENT,
                ends_on__isnull=True,
            ).first()

            if current:
                current.ends_on = timezone.now()
                current.save(update_fields=["ends_on", "updated_at"])

            VehiclePlate.objects.create(
                vehicle=vehicle,
                plate=plate,
                kind=VehiclePlate.CURRENT,
                changed_by=system_user,
            )

        return vehicle

    def run(self):
        conn = self._connect()

        try:
            # Novo fluxo: BDTs são a fonte da verdade para o --limit
            bdts = self._fetch_bdts(conn)
            self.stats.bdts_read = len(bdts)

            fleet_ids = {row["fleet_id"] for row in bdts if row.get("fleet_id")}
            
            # Identificamos os motoristas REAIS dos BDTs
            bdt_user_ids = {row["user_id"] for row in bdts if row.get("user_id")}

            fleets = self._fetch_fleets(conn, fleet_ids)
            self.stats.fleets_read = len(fleets)

            # Veículos podem ter um usuário associado diretamente na tabela fleets
            fleet_user_ids = {row["user_id"] for row in fleets if row.get("user_id")}
            
            # Buscamos todos no Hórus para ter em memória (futuro e diagnóstico)
            all_user_ids = bdt_user_ids.union(fleet_user_ids)

            users = self._fetch_users(conn, all_user_ids)
            self.stats.drivers_read = len(users)

            # Dry run termina AQUI, ANTES de qualquer escrita no banco
            if self.dry_run:
                # --- INÍCIO DO DIAGNÓSTICO TEMPORÁRIO ---
                if bdts:
                    print("\n" + "="*50)
                    print("DIAGNÓSTICO BDT (--dry-run ativado)")
                    print("="*50)
                    
                    for b in bdts:
                        print(f"--- BDT ID: {b.get('id')} ---")
                        print(f"management_id: {b.get('management_id')}")
                        print(f"fleet_id     : {b.get('fleet_id')}")
                        print(f"user_id      : {b.get('user_id')}")
                        print(f"adm_id       : {b.get('adm_id')}")
                        print(f"started_at   : {b.get('started_at')}")
                        print(f"ended_at     : {b.get('ended_at')}")
                        print(f"started_km   : '{b.get('started_km')}'")
                        print(f"ended_km     : '{b.get('ended_km')}'")
                        print(f"active       : {b.get('active')}")
                        print(f"created_at   : {b.get('created_at')}")
                        print(f"updated_at   : {b.get('updated_at')}")
                        print(f"service_id   : {b.get('service_id')}")
                        print(f"sector_id    : {b.get('sector_id')}")
                        print(f"note         : '{b.get('note')}'")
                        print("")
                        
                        # Buscar veículo correspondente
                        veiculo = next((f for f in fleets if f.get('id') == b.get('fleet_id')), None)
                        if veiculo:
                            print(f"  [VEÍCULO VINCULADO]")
                            print(f"  fleet_id     : {veiculo.get('id')}")
                            print(f"  plate        : '{veiculo.get('plate')}'")
                            print(f"  special_plate: '{veiculo.get('special_plate')}'")
                            print("")

                    if users:
                        print("--- USUÁRIOS ENCONTRADOS ---")
                        for u in users:
                            role = "MOTORISTA DO BDT" if u.get("id") in bdt_user_ids else "OUTRO (EX: USUÁRIO DA FROTA)"
                            print(f"user_id   : {u.get('id')} [{role}]")
                            print(f"first_name: '{u.get('first_name')}'")
                            print(f"last_name : '{u.get('last_name')}'")
                            print(f"document  : '{u.get('document')}'")
                            print("-" * 20)
                            
                    print("="*50 + "\n")
                # --- FIM DO DIAGNÓSTICO TEMPORÁRIO ---
                
                return self.stats

            system_user = self._system_user()
            vehicle_status = self._vehicle_status()

            with transaction.atomic():
                for row in users:
                    # ATENÇÃO: Criamos/atualizamos o model Driver SOMENTE para motoristas de BDT
                    if row["id"] in bdt_user_ids:
                        self._sync_driver(row)

                for row in fleets:
                    self._sync_vehicle(
                        row,
                        system_user,
                        vehicle_status,
                    )

            # Chama o BDTSyncWorker apenas se houver BDTs e NÃO for dry run
            if bdts:
                from apps.fleet.sync_bdt import BDTSyncWorker
                worker = BDTSyncWorker(bdts)
                worker_resumo = worker.run(managements_map={self.management_id: "Lei Seca"})
                
                self.stats.bdts_created = worker_resumo.get("criados", 0)
                self.stats.bdts_updated = worker_resumo.get("atualizados", 0)

            return self.stats

        finally:
            conn.close()
