# Ski Club Manager

**Software Development & DevOps | Individual Assignments 1 and 2**  
Alicia Mueller Reglero | IE University

*Managing the trip is one thing. Managing everyone going is another.*

## Why I built this

Organising ski trips for a university club has made me realise that the difficult part isn't necessarily choosing the destination or planning the dates. It's everything that happens once registrations open.

Places fill up quickly, payments arrive at different times, waiting lists keep changing, and room assignments depend on who has actually confirmed their place.

I built Ski Club Manager around those challenges: a small web application that keeps registrations, payments and accommodation connected, without making the underlying system unnecessarily complicated.

In Assignment 1 it was one Flask app in one container. For Assignment 2 it is split along the seam drawn then: **Trip Management** and **Room Allocation** are two Flask services, each with its own database, and a small **UI** container serves the web pages. Docker Compose runs all of them together.

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

The two domains from Assignment 1 now run as separate services. The browser only talks to the UI container; nginx there serves the pages and forwards API calls.

```text
                    Browser
                       |
            UI  (nginx, port 8080)
            pages + /health
               |              |
        /trip-api/*       /room-api/*
               |              |
   Trip Management  <----  Room Allocation
     (Flask, 8001)   HTTP    (Flask, 8002)
          |         ---->         |
       trips.db    release     rooms.db
   trips, registrations     rooms, room_assignments,
                            roommate_preferences

   SQL Server + db-init (being introduced, see below)
```

**Trip Management** owns `trips` and `registrations`: capacity, payments, cancellations and waiting-list order.

**Room Allocation** owns `rooms`, `room_assignments` and `roommate_preferences`. It never reads Trip Management's tables. When it needs to know whether a trip or registration exists, `_trip_exists` and `_get_registration` call `GET /trips/<id>` and `GET /registrations/<id>` on `TRIPS_URL`.

**Cancelling** a registration is the one call in the other direction: Trip Management calls Room Allocation's `POST /registrations/<id>/release` inside its own transaction. If Room Allocation is down, the cancel is rolled back and the organiser sees an error, so a cancelled student never keeps a bed.

**UI** is plain HTML, CSS and JavaScript served by nginx. Because the browser only ever talks to nginx, the services need no CORS settings.

### Databases

Each service still writes its own SQLite file (`trips.db`, `rooms.db`) to a Docker volume, so their data is already separate. The move to SQL Server has started: compose runs a `sqlserver` container and a one-shot `db-init` job that creates a `trips` and a `rooms` database with the same tables, from `services/db-init/01-trips.sql` and `02-rooms.sql`. Every statement there only creates what is missing, so `db-init` is safe to run on every start. The services are switched over to SQL Server in a later step.

Design choices and alternatives are explained in [ADR.md](ADR.md).

## 3. Getting started

### Run everything with Docker Compose

Requirements: Docker with Compose.

```bash
git clone https://github.com/aliciaamueller/skitripplanner.git
cd skitripplanner
cp .env.example .env        # then set MSSQL_SA_PASSWORD in .env
docker compose up --build
```

Open **http://localhost:8080**. Each service is also reachable directly: Trip Management on **http://localhost:8001**, Room Allocation on **http://localhost:8002**.

`.env` is ignored by Git, so the SQL Server password is never committed. Compose stops with a clear message if it is missing. Data lives in named volumes (`trips-data`, `rooms-data`, `sqlserver-data`) and survives `docker compose down`; `docker compose down -v` deletes it.

### Run a service directly

Each service has its own `requirements.txt` and starts with `python app.py`. For example, both services side by side:

```bash
cd services/trip-management
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PORT=8001 ROOMS_URL=http://localhost:8002 python app.py
```

```bash
cd services/room-allocation
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PORT=8002 TRIPS_URL=http://localhost:8001 python app.py
```

Each service creates its tables on startup and keeps existing data. The UI needs nginx, so it runs through Docker only.

### Configuration

| Service | Variable | Default | Description |
|---|---|---|---|
| Trip Management | `PORT` | `8000` | Port the service listens on |
| Trip Management | `DATA_DIR` | `./data` (`/data` in the image) | Folder for `trips.db` |
| Trip Management | `ROOMS_URL` | `http://room-allocation:8000` | Room Allocation, called when a registration is cancelled |
| Room Allocation | `PORT` | `8000` | Port the service listens on |
| Room Allocation | `DATA_DIR` | `./data` (`/data` in the image) | Folder for `rooms.db` |
| Room Allocation | `TRIPS_URL` | `http://trip-management:8000` | Trip Management, asked about trips and registrations |
| Both services | `GIT_SHA` | `dev` | Version reported by `/health` |
| UI | `PORT` | `8080` | Port nginx listens on |
| UI | `TRIPS_URL` | `http://trip-management:8000` | Where `/trip-api/` is forwarded |
| UI | `ROOMS_URL` | `http://room-allocation:8000` | Where `/room-api/` is forwarded |
| SQL Server, db-init | `MSSQL_SA_PASSWORD` | none, set in `.env` | SQL Server `sa` password |

**Database paths:** `$DATA_DIR/trips.db` and `$DATA_DIR/rooms.db`, which is `/data/...` inside each container, on that service's volume.

Every container answers `GET /health` with HTTP 200, so the cloud can check that it is alive.

## 4. Testing and reliability

Each service has its own tests, using **pytest** and **pytest-cov**. They run against temporary SQLite files, so they never touch real data. Room Allocation's tests replace the HTTP calls to Trip Management with an in-memory fake, so they test room rules without a running service.

Run one service's tests with coverage (from inside `services/trip-management` or `services/room-allocation`):

```bash
pip install -r requirements.txt pytest pytest-cov
python -m pytest --cov=. --cov-report=term-missing
```

### Recorded test results (2026-11-21)

**Trip Management: 47 tests. Room Allocation: 33 tests.** Business-logic coverage:

```text
Name                 Stmts   Miss  Cover
----------------------------------------
trip_management.py     150      0   100%
trip_statistics.py      14      0   100%
room_allocation.py     141      6    96%
```

Line coverage is not proof that every combination of rules is tested; the testing priorities are explained in ADR 4.

### Continuous integration

`.github/workflows/ci.yml` runs on every push. The `test` job runs ruff and pytest for each service. The `images` job only starts if the tests pass; it builds the three images and, on `main` only, pushes them to GitHub Container Registry tagged with the commit SHA.

### Preventing overbooking

One test starts **10 simultaneous registrations for a trip with only 2 available places**. The expected result is two reserved places and eight waitlisted students. `register_student` opens a `BEGIN IMMEDIATE` transaction before checking capacity, so simultaneous requests cannot reserve the same last places. Time-dependent tests use `monkeypatch` to simulate payment deadlines without waiting 48 hours.

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

## 5. Engineering decisions

A few decisions were particularly important during development.

**Keeping the implementation simple.** Flask and Python's built-in `sqlite3` module were sufficient for this project's scope, and the services call each other with the standard library's `urllib`, so the split added no new dependency. Using direct SQL also makes the database constraints and queries easier to follow.

**Preserving registration history.** Cancelled registrations are retained instead of deleted. A partial unique index prevents duplicate active registrations while allowing students to register again after cancelling.

**Handling simultaneous requests safely.** Database transactions protect capacity checks and registration updates, rather than assuming that registrations will always happen one at a time.

**Keeping responsibilities separate.** Trip Management and Room Allocation each own their database and only reach the other through its HTTP endpoints. Room counts were taken out of the trip statistics because the two tables now live in different databases.

**Patterns that support the split.** Three patterns from class are in the code because each one protects the boundary between the two domains. Each domain module works as a facade: the rest of the app changes a domain only by calling its public functions, such as `register_student` or `assign_student`, which later become that service's endpoints. Cancellation uses an observer: `app.py` registers `release_room` with `on_registration_cancelled`, so `trip_management.py` announces the cancellation and does not know that a Room Allocation service exists. Room Allocation reads Trip Management data only through two adapter functions, `_trip_exists` and `_get_registration`. In the split they were the only code that had to change: they now call Trip Management over HTTP instead of reading the shared database. `get_connection` in `db.py` also acts as a simple factory, so every connection is set up the same way.

**Avoiding unnecessary infrastructure.** Payment expiry is still checked during relevant operations rather than by a background job, so each service stays a single process.

These decisions, including alternatives and consequences, are documented in [ADR.md](ADR.md).

## 6. Project structure

```text
skitripplanner/
├── services/
│   ├── trip-management/      Trip Management service
│   │   ├── app.py            HTTP endpoints, calls Room Allocation on cancel
│   │   ├── trip_management.py  trips, registrations, payments, waiting list
│   │   ├── trip_statistics.py  numbers for the organiser overview
│   │   ├── config.py, db.py, schema.sql
│   │   ├── tests/
│   │   ├── requirements.txt, pytest.ini
│   │   └── Dockerfile
│   ├── room-allocation/      Room Allocation service
│   │   ├── app.py            HTTP endpoints
│   │   ├── room_allocation.py  rooms, assignments, roommate preferences
│   │   ├── config.py, db.py, schema.sql
│   │   ├── tests/
│   │   ├── requirements.txt, pytest.ini
│   │   └── Dockerfile
│   ├── UI/                   nginx + static pages
│   │   ├── site/             index, organiser, trip, my-trip pages
│   │   ├── nginx.conf.template
│   │   └── Dockerfile
│   └── db-init/              SQL Server scripts run by the db-init job
│       ├── 01-trips.sql
│       └── 02-rooms.sql
├── .github/workflows/ci.yml  tests, then image builds
├── docker-compose.yml        the whole system locally
├── .env.example              the variables .env must set
├── container/                professor-provided Assignment 1 template and checker
├── ADR.md
├── AI_USAGE.md
├── ASSIGNMENT_BRIEF.md
└── README.md
```

## 7. Development and documentation

The project was developed incrementally, with Git commits recording changes to the application, tests and documentation.

The supporting documents provide more detail:

- [ADR.md](ADR.md): architectural decisions, alternatives and consequences.
- [AI_USAGE.md](AI_USAGE.md): use of ChatGPT and Claude Code, including prompts, accepted or modified suggestions, and explanations of the resulting code.
- [ASSIGNMENT_BRIEF.md](ASSIGNMENT_BRIEF.md): the Assignment 1 requirements.

The current implementation focuses on the two required domains. Editing existing trips and automatic roommate matching are possible future extensions, rather than dependencies of the existing workflow.