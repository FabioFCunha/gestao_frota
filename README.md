# Gestão de Frotas

Backend inicial do sistema interno de Gestão de Frotas.

## Execução para desenvolvimento

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

O painel administrativo fica em `http://127.0.0.1:8000/admin/` e a API inicial em `http://127.0.0.1:8000/api/`.

## Banco de dados

Na ausência de variáveis `POSTGRES_*`, o projeto usa SQLite exclusivamente para desenvolvimento local. Em produção, defina as variáveis indicadas em `.env.example` para usar PostgreSQL.

## Backup PostgreSQL

Exemplo: `pg_dump -Fc -U frotas -d frotas > frotas-AAAA-MM-DD.dump`.

Para restaurar em banco vazio: `pg_restore -U frotas -d frotas --clean --if-exists frotas-AAAA-MM-DD.dump`.

Faça backups diários, mantenha cópia em armazenamento institucional separado e teste restaurações periodicamente.

## Auditoria da carga ADM do Hórus

`python manage.py dry_run_horus_adm_fleets` é somente leitura: precisa de rede tanto para o Hórus quanto para o banco de destino configurado no Django. Execute-o em um host que alcance ambos; não presuma que a VPS tenha rota para o IP privado do Hórus. Quando isso não for possível, execute a exportação somente leitura em um Windows com acesso ao Hórus e transfira apenas o relatório, sem credenciais, para comparação no destino. O comando não cria veículos nem vincula candidatos encontrados apenas por placa.
