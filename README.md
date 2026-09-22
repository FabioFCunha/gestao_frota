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
