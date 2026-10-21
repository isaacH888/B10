# Development setup and command status

Updated October 5, 2026. React/Vite + Flask + MySQL scaffolding is approved.
Shared shells exist; pricing/orders/auth/schema/provider features remain unimplemented.

## Prerequisites

Use Node 22 (at least 22.12) and Python 3.12 for the team/CI baseline. Local checks
used available Node 25.9.0 and Python 3.9.6; that does not verify the target CI runtimes.
Docker with Compose, or an independently installed MySQL 8.4, is needed for the DB
probe. Neither Docker nor MySQL is available on the current machine. Source:
[Vite requirements](https://vite.dev/guide/) and [Flask installation](https://flask.palletsprojects.com/en/stable/installation/).

The following commands are for macOS/Linux. Windows users use their Python launcher
and `backend\.venv\Scripts\python.exe` for the equivalent virtual-environment commands.

## Install from the repository root

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
npm ci --prefix frontend

# Keep existing private settings; templates contain no working credentials.
cp -n backend/.env.example backend/.env
cp -n frontend/.env.example frontend/.env
```

The locked Python toolchain contains shell dependencies, pytest and foundation
validators. `backend/requirements.in` and `requirements-foundation.in` record direct
constraints; review dependency updates and regenerate the lock in a clean environment.
Commit locks, not virtual environments or node_modules.

## Run independently in two terminals

Backend, starting from the repository root:

```sh
cd backend
.venv/bin/python -m flask --app app:create_app run --host 127.0.0.1 --port 5000
```

Frontend, starting from the repository root:

```sh
cd frontend
npm run dev
```

Open `http://localhost:5173` and select Check backend connection. This is a development
shell, not the customer website or dashboard. `/api/v1/live` is process liveness;
`/api/v1/health` checks MySQL connectivity and returns 503 while unconfigured/unavailable.
A 200 DB probe does not establish that Bryson's domain migrations have run.

Backend loads only `backend/.env` without overriding process variables. Vite loads
only its frontend environment; expose only `VITE_API_BASE_URL` there. Origins are
validated explicitly. Shared shell settings are documented in [configuration.md](configuration.md).

## Optional local MySQL infrastructure

After Docker/Compose is installed, copy the root template without overwriting local
settings, then fill private DB values before running Compose:

```sh
cp -n .env.example .env
docker compose config --quiet
docker compose up -d mysql
docker compose ps
```

Use matching DB_NAME/DB_USER/DB_PASSWORD in root and backend environments. Set
MYSQL_ROOT_PASSWORD only in the private root environment for local infrastructure.
The port is loopback-only and the named volume persists data. These variables
initialize a fresh volume; changing them later does not rotate an existing MySQL user.
Do not delete a volume to repair credentials without agreeing on data preservation.

Compose creates only the server and empty development database/user. Bryson's ERD,
migrations, models, seeds and migration command are still required. No schema or
real customer data is provided by this scaffold. Docker commands were not executable
on the current host and are not recorded as passed.

## Checks available now

```sh
backend/.venv/bin/python scripts/check_foundation.py
backend/.venv/bin/python -m pytest -c backend/pytest.ini -q
npm run build --prefix frontend
git diff --check
curl --fail-with-body http://localhost:5000/api/v1/live
curl -i http://localhost:5000/api/v1/health
```

To require the real MySQL check after configuring a disposable DB:

```sh
cd backend
RUN_DATABASE_INTEGRATION=1 .venv/bin/python -m pytest -q -m database
```

That test reads process DB settings, so export the private values in the test terminal
rather than assuming the test loads backend/.env. Normal shell startup does load it.
The default test run skips this check when no disposable DB is provided.

The shared CI workflow runs standards/example/link/template checks, backend tests
with disposable MySQL and the frontend build. Check actual results in GitHub Actions;
there is no deployment job. See [foundation-validation.md](foundation-validation.md).

## Remaining owner commands

Anh supplies pricing/order tests; Shourya supplies auth/email/provider checks;
Dillion/Aneena supply feature UI checks; Bryson supplies migration/seed/integrity
commands. Do not invent successful feature tests, migration results or external actions.
