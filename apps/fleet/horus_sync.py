import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import requests

from dataclasses import dataclass

logger = logging.getLogger(__name__)


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
    Agente Windows standalone que sincroniza BDTs de uma gestão do Hórus.
    Conecta-se ao Hórus (PostgreSQL local), extrai dados incrementais
    e envia via HTTPS POST para a VPS do Gestão de Frotas.
    """

    def __init__(
        self, dry_run=False, limit=None, *, management_id=None,
        state_file=None, lookback_days=None,
    ):
        self.dry_run = dry_run
        self.limit = limit
        if limit is not None and limit < 1:
            raise ValueError("O limite do lote deve ser maior que zero.")

        configured_management = int(os.getenv("HORUS_LEI_SECA_MANAGEMENT_ID", "49"))
        self.management_id = int(
            management_id if management_id is not None else configured_management
        )
        if self.management_id < 1:
            raise ValueError("O ID da gestão deve ser maior que zero.")
        self.management_name = {49: "Lei Seca", 125: "SEGOV - ADM"}.get(
            self.management_id, f"Gestão {self.management_id}"
        )
        configured_state = Path(os.getenv("HORUS_SYNC_STATE_FILE", ".bdt_horus_sync_state.json"))
        # Preserve the existing Lei Seca watermark. Other managements never
        # reuse it, even when the runner exports the original state path.
        self.state_file = Path(state_file) if state_file is not None else (
            configured_state if self.management_id == 49 else
            configured_state.with_name(
                f"{configured_state.stem}.management-{self.management_id}{configured_state.suffix}"
            )
        )
        self.lookback_days = int(
            lookback_days if lookback_days is not None else
            os.getenv("HORUS_BDT_LOOKBACK_DAYS", "90")
        )
        if self.lookback_days < 1:
            raise ValueError("A janela histórica deve ser maior que zero.")

        # API Configs
        # A read-only dry run must remain possible when the outbound secret is
        # intentionally unavailable in an interactive support session.
        self.api_url = os.getenv("VPS_API_URL", "").rstrip("/")
        self.api_token = os.getenv("VPS_SYNC_TOKEN", "")
        if not self.dry_run and (not self.api_url or not self.api_token):
            missing = "VPS_API_URL" if not self.api_url else "VPS_SYNC_TOKEN"
            raise RuntimeError(f"Variável de ambiente obrigatória não configurada: {missing}")

        self.stats = SyncStats()

    def _required_env(self, name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"Variável de ambiente obrigatória não configurada: {name}")
        return value

    def _connect(self):
        conn = psycopg.connect(
            host=self._required_env("HORUS_DB_HOST"),
            port=int(os.getenv("HORUS_DB_PORT", "5432")),
            dbname=self._required_env("HORUS_DB_NAME"),
            user=self._required_env("HORUS_DB_USER"),
            password=self._required_env("HORUS_DB_PASSWORD"),
            connect_timeout=int(os.getenv("HORUS_DB_CONNECT_TIMEOUT", "10")),
        )
        conn.read_only = True
        conn.autocommit = False
        return conn

    def _load_cursor(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError) as exc:
                raise RuntimeError("Estado de sincronização inválido; arquivo preservado.") from exc
            if not isinstance(data, dict):
                raise RuntimeError("Estado de sincronização inválido; arquivo preservado.")
            if data.get("management_id", 49) != self.management_id:
                raise RuntimeError(
                    "O cursor pertence a outra gestão. Use um arquivo de estado separado."
                )
            try:
                dt = datetime.fromisoformat(data["last_sync_updated_at"])
                last_id = data.get("last_sync_id", "00000000-0000-0000-0000-000000000000")
                return dt, last_id
            except Exception as e:
                logger.warning(f"Falha ao ler estado local. Fazendo sync completo de {self.lookback_days} dias. Erro: {e}")

        fallback_dt = datetime.now(timezone.utc) - timedelta(days=self.lookback_days)
        return fallback_dt, "00000000-0000-0000-0000-000000000000"

    def _save_cursor(self, max_updated_at, max_id):
        if max_updated_at and max_id and not self.dry_run:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "last_sync_updated_at": max_updated_at.isoformat(),
                "last_sync_id": str(max_id),
            }
            # Never leave a truncated watermark after a power loss or task kill.
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.state_file.parent,
                prefix=f"{self.state_file.name}.", suffix=".tmp", delete=False,
            ) as f:
                json.dump({
                    "management_id": self.management_id,
                    "last_sync_updated_at": max_updated_at.isoformat(),
                    "last_sync_id": str(max_id),
                }, f)
                f.flush()
                os.fsync(f.fileno())
                temporary_name = f.name
            os.replace(temporary_name, self.state_file)

    @staticmethod
    def _require_response(response, endpoint, expected_processed, *, vehicle_id=None):
        """Reject success HTTP responses that do not prove full acceptance."""
        if not isinstance(response, dict):
            raise RuntimeError(f"Resposta inválida de {endpoint}: JSON objeto esperado.")
        if vehicle_id is not None:
            if response.get("result") not in {"created", "updated"}:
                raise RuntimeError(f"Veículo {vehicle_id} não foi confirmado pela API: {response!r}")
            if str(response.get("external_id")) != str(vehicle_id):
                raise RuntimeError(f"API confirmou veículo externo divergente: {response!r}")
            return

        required = {"processados", "criados", "atualizados"}
        missing = required.difference(response)
        if missing:
            raise RuntimeError(f"Resposta incompleta de {endpoint}; faltam: {sorted(missing)}")
        try:
            processed = int(response["processados"])
            created = int(response["criados"])
            updated = int(response["atualizados"])
            failures = int(response.get("falhas", 0))
            unchanged = int(response.get("inalterados", 0))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Contadores inválidos de {endpoint}: {response!r}") from exc
        if processed != expected_processed or failures or created + updated + unchanged != expected_processed:
            raise RuntimeError(
                f"Confirmação parcial de {endpoint}: esperado={expected_processed}, recebido={response!r}"
            )

    def _fetch_bdts(self, conn, last_updated_at, last_id):
        # A janela de segurança atua no LIMITE SUPERIOR para ignorar commits em andamento.
        safe_now = datetime.now(timezone.utc) - timedelta(minutes=15)

        sql = """
            SELECT
                b.id, b.management_id, b.fleet_id, b.user_id, b.adm_id,
                b.started_at, b.started_km, b.ended_at, b.ended_km,
                b.latitude_match, b.longitude_match, b.latitude_retreat,
                b.longitude_retreat, b.note, b.active, b.created_at,
                b.updated_at, b.service_id, b.sector_id
            FROM public.bdtds b
            WHERE b.management_id = %s
              AND (
                  COALESCE(b.updated_at, b.created_at) > %s
                  OR (COALESCE(b.updated_at, b.created_at) = %s AND b.id::text > %s)
              )
              AND COALESCE(b.updated_at, b.created_at) <= %s
            ORDER BY COALESCE(b.updated_at, b.created_at) ASC, b.id::text ASC
        """
        params = [self.management_id, last_updated_at, last_updated_at, last_id, safe_now]
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
            SELECT f.id, f.plate, f.special_plate
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
            SELECT u.id, u.first_name, u.last_name, u.document
            FROM public.users u
            WHERE u.id = ANY(%s)
        """
        with conn.cursor() as cursor:
            cursor.execute(sql, (list(user_ids),))
            columns = [item.name for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _post_data(self, endpoint, payload):
        if not payload:
            return None

        url = f"{self.api_url}/api/sync/{endpoint}/"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

        def json_serial(obj):
            if isinstance(obj, (datetime)):
                return obj.isoformat()
            return str(obj)

        data = json.dumps(payload, default=json_serial)

        for attempt in range(3):
            try:
                resp = requests.post(url, data=data, headers=headers, timeout=(10, 120))

                # Falha rápida e explícita para erros do cliente (4xx)
                if 400 <= resp.status_code < 500:
                    logger.error(f"Erro cliente {resp.status_code} ao enviar {endpoint}: {resp.text}")
                    resp.raise_for_status()

                if resp.status_code in (200, 201):
                    return resp.json()

                resp.raise_for_status()

            except requests.exceptions.RequestException as e:
                # Retenta somente se não for erro 4xx
                if isinstance(e, requests.exceptions.HTTPError) and 400 <= e.response.status_code < 500:
                    raise

                if attempt == 2:
                    logger.error(f"Falha definitiva ao enviar {endpoint} após 3 tentativas: {e}")
                    raise
                logger.warning(f"Falha transitória ao enviar {endpoint} ({e}). Retentando em 5s...")
                time.sleep(5)

        raise RuntimeError(f"API não retornou confirmação para {endpoint}.")

    def run(self):
        conn = self._connect()
        try:
            last_updated_at, last_id = self._load_cursor()
            print(f"Gestão: {self.management_id} — {self.management_name} | Estado: {self.state_file}")
            print(f"Buscando BDTs com atualizações > {last_updated_at} (ou id > {last_id})")

            bdts = self._fetch_bdts(conn, last_updated_at, last_id)
            self.stats.bdts_read = len(bdts)

            if not bdts:
                print("Nenhum BDT novo ou alterado encontrado.")
                return self.stats

            fleet_ids = {row["fleet_id"] for row in bdts if row.get("fleet_id")}
            user_ids = {row["user_id"] for row in bdts if row.get("user_id")}

            fleets = self._fetch_fleets(conn, fleet_ids)
            self.stats.fleets_read = len(fleets)

            users = self._fetch_users(conn, user_ids)
            self.stats.drivers_read = len(users)

            print(f"Encontrados: {len(bdts)} BDTs, {len(fleets)} Veículos, {len(users)} Motoristas")

            missing_fleets = fleet_ids - {row["id"] for row in fleets}
            missing_users = user_ids - {row["id"] for row in users}
            if missing_fleets or missing_users:
                raise RuntimeError(
                    "O Hórus referenciou IDs sem cadastro recuperável: "
                    f"veículos={len(missing_fleets)}, motoristas={len(missing_users)}. Cursor preservado."
                )

            if self.dry_run:
                for fleet in fleets:
                    print(f"Viatura de origem: {fleet['plate']} | ID Hórus: {fleet['id']}")
                for user in users:
                    name = f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
                    print(f"Motorista de origem: {name} | ID Hórus: {user['id']}")
                print("Dry Run finalizado. Nenhum dado enviado para a VPS.")
                return self.stats

            # 1. Sincronizar Veículos
            print("Enviando Veículos...")
            for f in fleets:
                v_payload = {
                    "external_id": f["id"],
                    "plate": f["plate"],
                    "special_plate": f["special_plate"] or "",
                    "management_name": self.management_name
                }
                resp = self._post_data("vehicles", v_payload)
                self._require_response(resp, "vehicles", 1, vehicle_id=f["id"])
                if resp["result"] == "created":
                    self.stats.fleets_created += 1
                else:
                    self.stats.fleets_updated += 1

            # 2. Sincronizar Motoristas
            print("Enviando Motoristas...")
            if users:
                drivers_payload = [
                    {
                        "external_id": u["id"],
                        "name": f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip(),
                        "registration": u.get("document", "")
                    }
                    for u in users
                ]
                resp = self._post_data("drivers", drivers_payload)
                self._require_response(resp, "drivers", len(users))
                self.stats.drivers_created += int(resp["criados"])
                self.stats.drivers_updated += int(resp["atualizados"])

            # 3. Sincronizar BDTs
            print("Enviando BDTs...")
            bdt_resp = self._post_data("bdts", bdts)
            self._require_response(bdt_resp, "bdts", len(bdts))
            self.stats.bdts_created += int(bdt_resp["criados"])
            self.stats.bdts_updated += int(bdt_resp["atualizados"])
            print(f"Resultado BDTs: {bdt_resp}")

            # 4. Atualizar cursor state (determinístico da última row)
            last_bdt = bdts[-1]
            max_updated = last_bdt.get("updated_at") or last_bdt.get("created_at")
            max_id = last_bdt.get("id")

            self._save_cursor(max_updated, max_id)
            print(f"Sincronização concluída. Cursor atualizado para {max_updated} / {max_id}")

            return self.stats

        finally:
            conn.close()

