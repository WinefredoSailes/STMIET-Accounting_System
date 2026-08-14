# STMIET Accounting System — Backend

Modular monolith for Seven-Trent Machineries Industrial Equipment Trading.
Design decisions live in `/docs/adr/` (ADR-009 modular monolith, ADR-010
Django + PostgreSQL, ADR-002 no force-balance, ADR-004 immutable journal,
ADR-005 GL derivation, ADR-013 Tue-Mon cycles, ADR-032 voucher forms,
ADR-033 payroll GL feed).

## Layout

```
backend/
  config/            project config (settings package, urls, wsgi/asgi)
  apps/
    core/            shared mixins, money, exceptions
    foundation/      COA, companies, segments, fiscal calendar  (Phase 1)
    sequences/       document numbering registry               (Phase 1)
    workflow/        approval state machine                    (Phase 1)
    posting/         journal engine, GL, posting rules         (Phase 1)
    ar/ ap/ cash/    bounded contexts (Phases 2-4)             (stubs)
    inventory/ fleet/ payroll/ assets/ tax/ reporting/         (stubs)
  requirements/      base / dev / prod
```

## Quick start

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements\dev.txt
Copy-Item .env.example .env          # edit SECRET_KEY etc.
python manage.py migrate
python manage.py import_coa --file ..\excel-files\COA-STMIET-2026.xlsx
python manage.py runserver
```

API docs: http://localhost:8000/api/schema/swagger-ui/
Admin: http://localhost:8000/admin/

## Tests

```powershell
pytest
```

The posting engine test suite (apps/posting/tests.py) is the contract for the
core invariants: no force-balance, immutable posted entries, atomic GL
projection, approval threshold, rule-driven canonical JEs (ADR-018).

## Environments

- `config.settings.dev`   — SQLite fallback, DEBUG on (default).
- `config.settings.prod`  — requires `DATABASE_URL` to PostgreSQL, strict HTTPS.
- `config.settings.test`  — in-memory SQLite, used by pytest.

PostgreSQL locally: use docker-compose (db) or point `DATABASE_URL` at a
running instance (postgres 17 present on this machine).
