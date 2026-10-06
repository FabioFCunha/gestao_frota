from django.core.management.base import BaseCommand
from django.db import transaction
from apps.fleet.models import Vehicle, Sector, BDT

class Command(BaseCommand):
    help = "Classifica os veiculos existentes nos macro setores ADM ou LEI SECA."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Executa a classificacao sem alterar o banco de dados.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        try:
            adm_sector = Sector.objects.get(slug="adm")
            lei_seca_sector = Sector.objects.get(slug="lei-seca")
        except Sector.DoesNotExist:
            self.stdout.write(self.style.ERROR("Setores 'adm' e 'lei-seca' nao encontrados. Rode as migrations primeiro."))
            return

        vehicles = Vehicle.objects.prefetch_related("bdts").all()

        total = vehicles.count()
        adm_count = 0
        lei_seca_count = 0
        a_confirmar_count = 0
        conflitos_count = 0
        
        would_alter = 0
        already_classified = 0

        with transaction.atomic():
            for vehicle in vehicles:
                # 1. Evidencia segura e persistida para ADM: 
                # A propria integracao de carga gravou a origem no campo notes.
                is_adm = bool(vehicle.notes and "Gestao: SEGOV - ADM" in vehicle.notes)
                
                # 2. Varredura completa nos BDTs para Lei Seca (e reforco para ADM)
                has_bdt_49 = False
                has_bdt_125 = False
                
                for bdt in vehicle.bdts.all():
                    if bdt.horus_management_id == 49:
                        has_bdt_49 = True
                    elif bdt.horus_management_id == 125:
                        has_bdt_125 = True
                
                if has_bdt_125:
                    is_adm = True
                
                is_lei_seca = has_bdt_49
                
                proposed_sector = None
                
                # Resolucao final das prioridades
                if is_adm and is_lei_seca:
                    # Existe conflito insoluvel
                    proposed_sector = None
                    conflitos_count += 1
                    a_confirmar_count += 1
                elif is_adm:
                    proposed_sector = adm_sector
                    adm_count += 1
                elif is_lei_seca:
                    proposed_sector = lei_seca_sector
                    lei_seca_count += 1
                else:
                    # Nenhuma evidencia conclusiva
                    proposed_sector = None
                    a_confirmar_count += 1
                
                if vehicle.sector == proposed_sector:
                    already_classified += 1
                elif vehicle.sector is not None:
                    # Nao sobrescreve silenciosamente um sector ja existente
                    conflitos_count += 1
                    # Apenas marcamos como conflito, nao alteramos o que ja estava classificado
                else:
                    would_alter += 1
                    if not dry_run:
                        vehicle.sector = proposed_sector
                        vehicle.save(update_fields=["sector", "updated_at"])

            self.stdout.write("=== CLASSIFICACAO DE VEICULOS POR SETOR ===\n")
            self.stdout.write(f"Total de veiculos: {total}\n")
            self.stdout.write(f"ADM:\n  {adm_count}\n")
            self.stdout.write(f"LEI SECA:\n  {lei_seca_count}\n")
            self.stdout.write(f"A CONFIRMAR:\n  {a_confirmar_count}\n")
            self.stdout.write(f"Conflitos:\n  {conflitos_count}\n")
            
            self.stdout.write(f"Alteracoes que seriam realizadas:\n  {would_alter}\n")
            self.stdout.write(f"Ja classificados corretamente:\n  {already_classified}\n")

            if dry_run:
                self.stdout.write(self.style.WARNING("\nDRY-RUN concluido. Nenhuma alteracao foi feita no banco."))
            else:
                self.stdout.write(self.style.SUCCESS("\nClassificacao concluida com sucesso."))
