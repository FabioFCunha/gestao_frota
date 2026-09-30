from django.core.management.base import BaseCommand, CommandError

from apps.fleet.horus_sync import HorusBDTSyncer


class Command(BaseCommand):
    help = "Sincroniza frota Lei Seca e BDTs do Hórus."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Consulta o Hórus sem gravar dados locais.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limita a quantidade de veículos processados.",
        )

    def handle(self, *args, **options):
        try:
            syncer = HorusBDTSyncer(
                dry_run=options["dry_run"],
                limit=options["limit"],
            )

            stats = syncer.run()

        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS("Sincronizacao concluida.")
        )

        self.stdout.write(
            f"Frotas lidas: {stats.fleets_read}"
        )
        self.stdout.write(
            f"Frotas criadas: {stats.fleets_created}"
        )
        self.stdout.write(
            f"Frotas atualizadas: {stats.fleets_updated}"
        )
        self.stdout.write(
            f"Usuarios lidos: {stats.drivers_read}"
        )
        self.stdout.write(
            f"Usuarios criados: {stats.drivers_created}"
        )
        self.stdout.write(
            f"Usuarios atualizados: {stats.drivers_updated}"
        )
        self.stdout.write(
            f"BDTs lidos: {stats.bdts_read}"
        )
        self.stdout.write(
            f"BDTs criados: {stats.bdts_created}"
        )
        self.stdout.write(
            f"BDTs atualizados: {stats.bdts_updated}"
        )
