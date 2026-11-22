# Ski Club Manager

**Software Development & DevOps | Individual Assignments 1 and 2**  
Alicia Mueller Reglero | IE University

*Managing the trip is one thing. Managing everyone going is another.*

**Live:** https://amuellerieu2024ui.z1.web.core.windows.net (the first visit after a quiet hour can take about a minute while Azure starts the services and wakes the databases)

## Why I built this

Organising ski trips for a university club has made me realise that the difficult part isn't necessarily choosing the destination or planning the dates. It's everything that happens once registrations open.

Places fill up quickly, payments arrive at different times, waiting lists keep changing, and room assignments depend on who has actually confirmed their place.

I built Ski Club Manager around those challenges: a small web application that keeps registrations, payments and accommodation connected, without making the underlying system unnecessarily complicated.

In Assignment 1 it was one Flask app in one container. For Assignment 2 it is split along the seam drawn then: **Trip Management** and **Room Allocation** are two Flask services, each with its own database, and the web pages are a static **UI** in `ui/` that calls both services from the browser. Docker Compose runs all of it together.

## 1. How it works

### Trip registration and payments

Each trip has a fixed number of places. When a student registers, the application checks availability and assigns one of four statuses:

| Status | Meaning |
|---|---|
| `pending_payment` | A place is reserved for 48 hours |
| `confirmed` | Payment has been confirmed |
| `waitlisted` | The trip is full, so the student joins the waiting list |
| `cancelled` | The registration was cancelled or the payment deadline expired |

When someone cancels or a payment deadline expires, the first student on the waiting list receives the available place and a new 48-hour payment window.

Expired reservations are processed whenever a registration, payment or cancellation is handled. This keeps the application within the single-process requirement without introducing background workers.

### Room allocation

Once payment is confirmed, organisers can create rooms with one to six beds, assign students and record roommate preferences.

The application checks that students are confirmed, rooms belong to the correct trip and no room exceeds its capacity. Cancelling a registration also releases the student's room assignment and removes any roommate preferences made by or naming that student.

### Dashboard

The **organiser** side gives an overview of each trip (available places, confirmed registrations, pending payments, waiting list) and a page per trip for registrations, payments, cancellations, rooms and roommate preferences.

The **My trip** side lets a student look up their own registration with their registration number and email, see their status and room, and keep a personal packing list.

## 2. Architecture

The two domains from Assignment 1 now run as separate services. The UI is static files; the browser loads them from nginx and then calls each service directly.

```text
                        Browser
            loads ui/ from nginx (port 8080)
               |                       |
     TRIPS_URL (config.js)     ROOMS_URL (config.js)
               |                       |
   Trip Management  <------  Room Allocation
     (Flask, 8001)    HTTP     (Flask, 8002)
          |          ------>          |
  trips database    release   rooms database
   trips, registrations       rooms, room_assignments,
                              roommate_preferences

   both databases: one SQL Server (compose) / Azure SQL serverless (cloud)
```

**Trip Management** owns `trips` and `registrations`: capacity, payments, cancellations and waiting-list order.

**Room Allocation** owns `rooms`, `room_assignments` and `roommate_preferences`. It never reads Trip Management's tables. When it needs to know whether a trip or registration exists, `_trip_exists` and `_get_registration` call `GET /trips/<id>` and `GET /registrations/<id>` on `TRIPS_URL`.

**Cancelling** a registration is the one call in the other direction: Trip Management calls Room Allocation's `POST /registrations/<id>/release` inside its own transaction. If Room Allocation is down, the cancel is rolled back and the organiser sees an error, so a cancelled student never keeps a bed.

**UI** is plain HTML, CSS and JavaScript in `ui/`. It reads the services' addresses from `ui/config.js`: locally the compose ports, on Azure the deploy pipeline writes the real URLs into that file. Because the page and the services have different origins, each service sends CORS headers that allow only the UI's origin (`CORS_ORIGIN`).

### Databases

Each service has its own SQL Server database and its own login, and neither login can open the other database:

- **Locally**, compose runs one `sqlserver` container and a one-shot `db-init` job. `db-init` runs `db/init.sql`, which creates the `trips` and `rooms` databases and the logins `trips_app` and `rooms_app`, each a user in its own database only. The script only creates what is missing, so it runs on every start.
- **Tables** are created by each service's **migrations**: numbered SQL files in `services/<service>/migrations/` (`001_init.sql`, ...). At startup, before serving requests, `db.migrate()` applies every file not yet recorded in the `schema_migrations` table, in order, each in its own transaction with its record. A second start applies nothing (the log says `0 migration(s) applied now`). Applied files are never edited; changes go in a new file.
- **Connections** come from `DATABASE_URL`. A failed connect is retried with a growing wait (1 s, 2 s, 4 s, ...), longer at startup, because the Azure serverless database pauses when idle and takes up to about a minute to resume.

Design choices and alternatives are explained in [ADR.md](ADR.md).

## 3. Getting started

### Run everything with Docker Compose

Requirements: Docker with Compose.

```bash
git clone https://github.com/aliciaamueller/skitripplanner.git
cd skitripplanner
cp .env.example .env        # then set the three passwords in .env
docker compose up --build
```

Open **http://localhost:8080**. Each service is also reachable directly: Trip Management on **http://localhost:8001**, Room Allocation on **http://localhost:8002**.

`.env` is ignored by Git, so the database passwords are never committed. Compose stops with a clear message if one is missing. Both databases live in the `sqlserver-data` volume and survive `docker compose down`; `docker compose down -v` deletes them.

### Run a service directly

Each service has its own `requirements.txt` and starts with `python app.py`. It needs a SQL Server with its database and login, for example the compose one: `docker compose up -d db-init` starts SQL Server, creates both databases and logins, and exits. Then, with the passwords from your `.env`:

```bash
cd services/trip-management
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PORT=8001 ROOMS_URL=http://localhost:8002 \
  DATABASE_URL='mssql://trips_app:<TRIPS_DB_PASSWORD>@localhost:1433/trips' python app.py
```

```bash
cd services/room-allocation
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PORT=8002 TRIPS_URL=http://localhost:8001 \
  DATABASE_URL='mssql://rooms_app:<ROOMS_DB_PASSWORD>@localhost:1433/rooms' python app.py
```

Each service applies its pending migrations on startup and keeps existing data. To use the UI with services started this way, serve the `ui/` folder on port 8080 (for example `python3 -m http.server 8080 -d ui`), so its origin matches the default `CORS_ORIGIN`.

### Configuration

| Service | Variable | Default | Description |
|---|---|---|---|
| Trip Management | `PORT` | `8000` | Port the service listens on |
| Trip Management | `DATABASE_URL` | none (secret) | `mssql://trips_app:<password>@<host>:1433/trips`; characters like `@` `/` `:` in the password must be percent-encoded |
| Trip Management | `ROOMS_URL` | `http://room-allocation:8000` | Room Allocation, called when a registration is cancelled |
| Room Allocation | `PORT` | `8000` | Port the service listens on |
| Room Allocation | `DATABASE_URL` | none (secret) | `mssql://rooms_app:<password>@<host>:1433/rooms` |
| Room Allocation | `TRIPS_URL` | `http://trip-management:8000` | Trip Management, asked about trips and registrations |
| Trip Management | `ROOMS_TIMEOUT_S` | `5` | Seconds to wait for Room Allocation |
| Room Allocation | `TRIPS_TIMEOUT_S` | `5` | Seconds to wait for Trip Management |
| Both services | `CORS_ORIGIN` | `http://localhost:8080` | The only origin browsers may call the service from (the UI) |
| Both services | `GIT_SHA` | `dev` | Version reported by `/health` |
| UI | `ui/config.js` | `http://localhost:8001`, `http://localhost:8002` | `TRIPS_URL` and `ROOMS_URL` the browser calls; rewritten at deploy time |
| sqlserver, db-init | `MSSQL_SA_PASSWORD` | none, set in `.env` | SQL Server administrator password |
| db-init | `TRIPS_DB_PASSWORD` | none, set in `.env` | Password of the `trips_app` login |
| db-init | `ROOMS_DB_PASSWORD` | none, set in `.env` | Password of the `rooms_app` login |

Both services answer `GET /health` with 200 and `{"status": "ok", "db": "ok", "version": "<git sha>"}` when they can read and write their own database, and 503 otherwise. Every request is logged on stdout as one line with method, path, status and duration, for example `GET /trips 200 12ms`. The full description of every service, its variables and its calls is in `system.yaml`, and each service's endpoints are in its `openapi.yaml`.

## 4. Testing and reliability

Each service has its own tests, using **pytest** and **pytest-cov**. They run against a real SQL Server, but never against the service's own database: at the start, `tests/conftest.py` creates a throwaway `trips_test` or `rooms_test` database, applies the migrations to it with the real runner, and empties its tables before every test. Room Allocation's tests replace the HTTP calls to Trip Management with an in-memory fake, so they test room rules without a running service.

The tests find SQL Server through `TEST_DATABASE_URL`, an administrator login that may create databases. With the compose SQL Server running (`docker compose up -d sqlserver`, published on `127.0.0.1:1433` only), run one service's tests with coverage from inside `services/trip-management` or `services/room-allocation`:

```bash
pip install -r requirements.txt pytest pytest-cov
export TEST_DATABASE_URL='mssql://sa:<MSSQL_SA_PASSWORD>@localhost:1433/master'
python -m pytest --cov=. --cov-report=term-missing
```

### Recorded test results (2026-11-22, against SQL Server)

**Trip Management: 53 tests. Room Allocation: 38 tests.** Coverage of the business logic and the database code:

```text
Name                 Stmts   Miss  Cover
----------------------------------------
trip_management.py     151      0   100%
trip_statistics.py      14      0   100%
room_allocation.py     138      6    96%
db.py (trips)           91      6    93%
db.py (rooms)           91     13    86%
```

Line coverage is not proof that every combination of rules is tested; the testing priorities are explained in ADR 4.

### Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

- `test`: ruff and pytest for each service, against a throwaway SQL Server container started in the job with a random password made in that step and masked in the log (so no password is stored and CI never touches Azure SQL). Fails if the core modules are below 70% covered.
- `describe`: validates `system.yaml` against `system.schema.json` and both `openapi.yaml` files against the OpenAPI specification.
- `images`: after both, builds the two service images; on `main` only, pushes them to GitHub Container Registry tagged with the commit SHA.
- `deploy`: on `main` only, after all of the above (see section 5).

The cross-seam test, `services/trip-management/tests/test_cross_seam.py`, replaces Room Allocation with a real HTTP server started inside the test, and checks that cancelling calls `POST /registrations/{id}/release` and that the cancellation is rolled back when that server is down (ADR 9).

### Preventing overbooking

One test starts **10 simultaneous registrations for a trip with only 2 available places**. The expected result is two reserved places and eight waitlisted students. Before checking capacity, every change to a trip's registrations locks that trip's row (`SELECT ... WITH (UPDLOCK, HOLDLOCK)`), so a second request for the same trip waits until the first commits, and requests for other trips are not blocked. `assign_student` locks the room's row the same way, so two students cannot both take a room's last bed. Time-dependent tests use `monkeypatch` to simulate payment deadlines without waiting 48 hours.

### Assignment 1 container check

The professor's `container/run.sh` checks the single-container app from Assignment 1. Its passing run (2026-10-12) applied to the monolith, which is still in the history up to commit `1f6412a`:

```text
=== SDD Assignment 1 contract check ===
==> Repository shape                                PASS
==> Build from a clean context, no build args       PASS  (image 53 MB)
==> Start on PORT=8000 and reach it from the host   PASS
==> SQLite file under DATA_DIR                      PASS  (ski_club.db)
==> Data persists, and a second boot does not re-seed  PASS
==> PORT override is honoured (not hardcoded)       PASS
=== ALL CHECKS PASSED ===
```

## 5. Deployment on Azure

**Live URL:** https://amuellerieu2024ui.z1.web.core.windows.net

Everything runs in the Azure for Students subscription, in resource group `rg-amueller-ieu2024` (region `germanywestcentral`):

| Resource | Name | Billing |
|---|---|---|
| Container Apps environment (with its Log Analytics workspace) | `amueller-ieu2024-env` | pay per use |
| Container App, 0 to 1 replicas | `amueller-ieu2024-trip-management` | pay per use, nothing while scaled to zero |
| Container App, 0 to 1 replicas | `amueller-ieu2024-room-allocation` | pay per use, nothing while scaled to zero |
| Azure SQL logical server | `amueller-ieu2024-sql` | free |
| Serverless database, free offer, pauses after 60 min | `amueller-ieu2024-trip-management-db` | free offer |
| Serverless database, free offer, pauses after 60 min | `amueller-ieu2024-room-allocation-db` | free offer |
| Storage account with static website (the UI) | `amuellerieu2024ui` | pay per use |
| User-assigned managed identity for GitHub Actions | `amueller-ieu2024-github` | free |

Images come from GitHub Container Registry (`ghcr.io/aliciaamueller/skitripplanner-<service>:<commit sha>`), which is public, so Azure needs no registry password.

### How a deployment works

Every merge to `main` runs the `deploy` job, only after `test`, `describe` and `images` passed on that same commit:

1. It signs in to Azure as the managed identity `amueller-ieu2024-github` through OpenID Connect. Azure trusts it only for runs on `main` of this repository, with Contributor on the resource group only, so no Azure password exists anywhere.
2. It works out the addresses: the UI's from the storage account, the services' from the Container Apps environment's domain.
3. It creates or updates both Container Apps with the image of this commit, minimum 0 and maximum 1 replica, `DATABASE_URL` as a Container Apps secret, and `GIT_SHA`, `CORS_ORIGIN` (the UI's origin) and the other service's URL as plain variables. Each service applies its pending migrations when it starts.
4. It writes `ui/config.js` with the two services' URLs and uploads `ui/` to the `$web` container.
5. It calls `/health` on both services and fails the run unless both answer 200 within several minutes, which allows for a cold start and a paused database resuming.

### Initial setup (once, by hand)

`infra/azure-setup.sh` is the documented, repeatable initial setup. It needs the Azure CLI signed in to the Azure for Students subscription and the GitHub CLI signed in to this repository:

```bash
az login
az account set --subscription "Azure for Students"
gh auth login
LOCATION=germanywestcentral PROFESSOR=<professor's email> ./infra/azure-setup.sh
```

In order, it:

1. registers the resource providers and installs the `containerapp` CLI extension;
2. creates the resource group;
3. creates the managed identity, its federated credential for `repo:aliciaamueller/skitripplanner:ref:refs/heads/main`, and its Contributor role on the resource group;
4. creates the SQL server (admin password random, stored only as the GitHub secret `SQL_ADMIN_PASSWORD`), the "allow Azure services" firewall rule, and the two serverless databases on the free offer (General Purpose, Gen5, 0.5 to 1 vCore, auto-pause 60 minutes, 32 GB, locally redundant backups);
5. opens the firewall to this machine for a moment and creates one contained user per database (`trips_app`, `rooms_app`, each with `db_owner` on its own database only, so neither can open the other), then closes the firewall again and stores each service's `DATABASE_URL` as a GitHub secret;
6. creates the storage account and turns on its static website;
7. creates the Container Apps environment;
8. stores the identity's client, tenant and subscription IDs as GitHub secrets;
9. gives the professor the Reader role on the resource group.

Every password is generated by the script and goes straight into a GitHub secret; none is printed, written to a file or committed. After this, nothing is changed in the portal: the pipeline creates and updates the Container Apps and uploads the UI.

## 6. Engineering decisions

A few decisions were particularly important during development.

**Keeping the implementation simple.** Flask, plain SQL and one database driver (`pymssql`) are enough for this project's scope, and the services call each other with the standard library's `urllib`. `db.py` wraps `pymssql` in a small `Connection` with the same `execute(sql, params)` and `row["column"]` interface the SQLite code used, so the move to SQL Server changed the SQL dialect but not the shape of the domain code. Using direct SQL also makes the database constraints and queries easier to follow.

**Preserving registration history.** Cancelled registrations are retained instead of deleted. A partial unique index prevents duplicate active registrations while allowing students to register again after cancelling.

**Handling simultaneous requests safely.** Database transactions protect capacity checks and registration updates, rather than assuming that registrations will always happen one at a time.

**Keeping responsibilities separate.** Trip Management and Room Allocation each own their database and only reach the other through its HTTP endpoints. Room counts were taken out of the trip statistics because the two tables now live in different databases.

**Patterns that support the split.** Three patterns from class are in the code because each one protects the boundary between the two domains. Each domain module works as a facade: the rest of the app changes a domain only by calling its public functions, such as `register_student` or `assign_student`, which later become that service's endpoints. Cancellation uses an observer: `app.py` registers `release_room` with `on_registration_cancelled`, so `trip_management.py` announces the cancellation and does not know that a Room Allocation service exists. Room Allocation reads Trip Management data only through two adapter functions, `_trip_exists` and `_get_registration`. In the split they were the only code that had to change: they now call Trip Management over HTTP instead of reading the shared database. `get_connection` in `db.py` also acts as a simple factory, so every connection is set up the same way.

**Avoiding unnecessary infrastructure.** Payment expiry is still checked during relevant operations rather than by a background job, so each service stays a single process.

These decisions, including alternatives and consequences, are documented in [ADR.md](ADR.md).

## 7. Project structure

```text
skitripplanner/
├── services/
│   ├── trip-management/      Trip Management service
│   │   ├── app.py            HTTP endpoints, calls Room Allocation on cancel
│   │   ├── trip_management.py  trips, registrations, payments, waiting list
│   │   ├── trip_statistics.py  numbers for the organiser overview
│   │   ├── config.py, db.py  settings; connections and the migration runner
│   │   ├── migrations/       SQL Server schema, one numbered file per change
│   │   ├── tests/
│   │   ├── requirements.txt, pytest.ini
│   │   └── Dockerfile
│   └── room-allocation/      Room Allocation service
│       ├── app.py            HTTP endpoints
│       ├── room_allocation.py  rooms, assignments, roommate preferences
│       ├── config.py, db.py
│       ├── migrations/
│       ├── tests/
│       ├── requirements.txt, pytest.ini
│       └── Dockerfile
├── ui/                       static UI: pages, config.js, styles, images
├── db/
│   └── init.sql              local databases and one login per service
├── .github/workflows/ci.yml  tests, validation, images, deploy
├── infra/azure-setup.sh      one-time Azure setup
├── system.yaml, system.schema.json  machine-readable system description
├── docker-compose.yml        the whole system locally
├── .env.example              the variables .env must set
├── container/                professor-provided Assignment 1 template and checker
├── ADR.md
├── AI_USAGE.md
├── ASSIGNMENT_BRIEF.md
└── README.md
```

## 8. Development and documentation

The project was developed incrementally, with Git commits recording changes to the application, tests and documentation.

The supporting documents provide more detail:

- [ADR.md](ADR.md): architectural decisions, alternatives and consequences.
- [AI_USAGE.md](AI_USAGE.md): use of ChatGPT and Claude Code, including prompts, accepted or modified suggestions, and explanations of the resulting code.
- [ASSIGNMENT_BRIEF.md](ASSIGNMENT_BRIEF.md): the Assignment 1 requirements.

The current implementation focuses on the two required domains. Editing existing trips and automatic roommate matching are possible future extensions, rather than dependencies of the existing workflow.