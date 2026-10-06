from django.core.management.base import BaseCommand, CommandError

from apps.fleet.horus_sync import HorusBDTSyncer


class Command(BaseCommand):
    help = "Sincroniza as viaturas de uma gestão específica do Hórus."

    def add_arguments(self, parser):
        parser.add_argument(
            "--management-id",
            type=int,
            default=125,
            help="ID da gestão no Hórus (padrão: 125 - SEGOV - ADM).",
        )
        parser.add_argument(
            "--management-name",
            type=str,
            default="SEGOV - ADM",
            help="Nome usado no registro da sincronização.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Consulta o Hórus e mostra o que seria sincronizado, sem gravar.",
        )

    def handle(self, *args, **options):
        management_id = options["management_id"]
        management_name = options["management_name"]
        dry_run = options["dry_run"]

        try:
            syncer = HorusBDTSyncer(dry_run=dry_run)

            with syncer._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'fleets'
                          AND column_name = 'management_id'
                        """
                    )
                    if cursor.fetchone() is None:
                        raise CommandError(
                            "A tabela public.fleets do Hórus não possui management_id. "
                            "Não é seguro inferir a gestão por placa ou BDT."
                        )

                    cursor.execute(
                        """
                        SELECT f.id, f.plate, f.special_plate
                        FROM public.fleets f
                        WHERE f.management_id = %s
                        ORDER BY f.plate NULLS LAST, f.id
                        """,
                        [management_id],
                    )
                    fleets = [
                        {
                            "id": row[0],
                            "plate": row[1],
                            "special_plate": row[2],
                        }
                        for row in cursor.fetchall()
                    ]

            self.stdout.write(
                f"Hórus | Gestão {management_id} | {management_name}"
            )
            self.stdout.write(f"Viaturas encontradas: {len(fleets)}")

            if not fleets:
                self.stdout.write(
                    self.style.WARNING(
                        "Nenhuma viatura encontrada para esta gestão. "
                        "Nenhum dado foi alterado."
                    )
                )
                return

            for fleet in fleets:
                self.stdout.write(
                    f"- {fleet['plate'] or '(sem placa)'} | {fleet['id']}"
                )

            if dry_run:
                self.stdout.write(
                    self.style.SUCCESS(
                        "DRY-RUN concluído. Nenhuma viatura foi enviada para o Gestão de Frotas."
                    )
                )
                return

            created = 0
            updated = 0

            for fleet in fleets:
                response = syncer._post_data(
                    "vehicles",
                    {
                        "external_id": fleet["id"],
                        "plate": (fleet["plate"] or "").strip().upper(),
                        "special_plate": fleet["special_plate"] or "",
                        "management_name": management_name,
                    },
                )
                syncer._require_response(
                    response,
                    "vehicles",
                    1,
                    vehicle_id=fleet["id"],
                )

                if response["result"] == "created":
                    created += 1
                else:
                    updated += 1

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Sincronização concluída."))
            self.stdout.write(f"Gestão Hórus: {management_id} - {management_name}")
            self.stdout.write(f"Encontradas: {len(fleets)}")
            self.stdout.write(f"Criadas: {created}")
            self.stdout.write(f"Atualizadas: {updated}")

        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(str(exc)) from exc
