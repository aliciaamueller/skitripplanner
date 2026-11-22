# Architecture Decision Records — Ski Club Manager

## 1. Use Flask with raw sqlite3
Date: 2026-10-11
Status: Superseded by [7]
Context: The club runs around four trips a season with about 150 students per trip, and only one or two organisers use the app at a time. The assignment also requires one process, one container and SQLite.
Decision: Use Flask to serve server-rendered HTML pages, and Python's built-in `sqlite3` module with the schema written by hand in `schema.sql` instead of an ORM.
Alternatives considered: Django brings authentication, an admin interface and an ORM, which is far more than five tables and two domains need. FastAPI is a better fit for a JSON API, but this app mainly serves HTML forms. SQLAlchemy was rejected because with five tables I preferred writing the SQL myself so I could see every query and constraint.
Consequences: Only one runtime dependency (Flask), and the database is easy to inspect with plain SQL. The cost is that I write every query and every validation check myself, with no ORM to catch mistakes.

## 2. Scope Trip Management and Room Allocation as separate domains
Date: 2026-10-11
Status: Decided
Context: The app solves two different problems: Trip Management decides who gets a place, and Room Allocation decides where confirmed students sleep. Assignment 2 will split them into separate services, so the seam has to exist now.
Decision: Trip Management (`trip_management.py`, `trip_statistics.py`) owns `trips` and `registrations`; Room Allocation (`room_allocation.py`) owns `rooms`, `room_assignments` and `roommate_preferences`. Only trip IDs, registration IDs and a registration's status cross the boundary.
Alternatives considered: One large module would have been quicker to write at first, but registration and accommodation rules would end up mixed in the same functions, making the Assignment 2 split a rewrite rather than a cut.
Consequences: Four things still cross the seam and would become API calls or messages after the split: `room_allocation.py` reads Trip Management data, but only through two adapter functions, `_trip_exists` and `_get_registration`, the cancellation event (Room Allocation subscribes with `on_registration_cancelled`, an Observer, so Trip Management never writes to room tables), `get_trip_statistics` joins registrations with room assignments for the dashboard, and `get_trip_details` in `app.py` does the same to build the trip page.

## 3. Keep registration history and use plain IDs across the domain boundary
Date: 2026-10-11
Status: Decided
Context: Students can cancel and register again, unpaid places are only held for 48 hours, and the waiting list must keep registration order. The schema also has to respect the seam from ADR 2.
Decision: Registrations are never deleted; they move between `pending_payment`, `confirmed`, `waitlisted` and `cancelled`, with a partial unique index on `(trip_id, email)` that only applies to non-cancelled rows. Foreign keys are used inside each domain, but cross-domain references such as `room_assignments.registration_id` are plain integers checked in Python.
Alternatives considered: Deleting cancelled registrations would lose history. A normal `UNIQUE(trip_id, email)` would block a student from registering again after cancelling. Cross-domain foreign keys would tie the two domains together at the database level and break as soon as the tables live in different databases.
Consequences: The app has to validate cross-domain IDs itself and be careful to count `pending_payment` as a taken place but not as needing a room. Adding `pending_payment` later also needed a small table rebuild in `db.init_db`, because `CREATE TABLE IF NOT EXISTS` does not change an existing table's CHECK constraint.

## 4. Prioritise tests for the business rules
Date: 2026-10-12
Status: Superseded by [9]
Context: The assignment requires at least 70% coverage of the core business logic, and I wanted the tests to target the rules whose failure would actually hurt students, not just raise the percentage.
Decision: Use pytest with a fresh temporary SQLite database per test, and measure coverage only on `trip_management.py`, `trip_statistics.py` and `room_allocation.py`, prioritising capacity, the 48-hour deadline, cancellation, FIFO waitlist promotion, room rules and a ten-thread overbooking test.
Alternatives considered: Simple one-function-at-a-time tests with fixed inputs would have reached 70% faster, but would miss the bugs that appear when rules interact (expiry triggering promotion, cancellation freeing a room). Measuring coverage over every file including `app.py` was rejected because it mixes framework glue into a number that is meant to describe business logic.
Consequences: 62 tests pass with 100% line coverage on the core modules. Flask routes are tested more thinly in `test_app.py` (one full workflow, form validation and trip-ownership checks) and kept out of the reported figure, and there are no tests for template rendering or styling.

## 5. Leave out authentication and real payment processing
Date: 2026-10-12
Status: Decided
Context: A real club would need organiser accounts and online payment, but this assignment is about two separable backend domains running in one container.
Decision: Build an organiser-only tool with no login, where an organiser records that a payment was received, and expire unpaid reservations inside normal requests instead of with a background job.
Alternatives considered: Flask-Login with a users table would add a third area of functionality outside the two required domains. A real payment provider would need external credentials and webhooks, which breaks the "no external dependency" rule. A scheduled background job would release expired places automatically, but needs a second process, which §1c rules out.
Consequences: The app stays small and fully testable, but must not be exposed publicly without authentication. An expired reservation is only released when the next registration, payment or cancellation on that trip runs `_release_expired`, so the dashboard can briefly show a stale count.

## 6. Split along the ADR-2 seam: two services that call each other over HTTP
Date: 2026-11-17
Status: Decided
Context: Assignment 2 requires one service per domain, each with its own container and data, and at least one user flow that crosses the seam on the server side. ADR-2 had already named what crossed it: two adapter reads, the cancellation event, and two cross-domain reads for the dashboard and trip page.
Decision: The seam stayed where ADR-2 put it. Room Allocation asks Trip Management `GET /trips/{id}` and `GET /registrations/{id}` (only `_trip_exists` and `_get_registration` changed), and cancelling a registration calls Room Allocation's `POST /registrations/{id}/release` inside Trip Management's transaction; if that call fails or times out (`ROOMS_TIMEOUT_S`), the cancellation is rolled back with a clear error. The two cross-domain reads moved to the static UI, which calls both services and joins names and rooms in the browser, showing the trip without rooms when Room Allocation is down.
Alternatives considered: Letting the cancellation succeed and retrying the release later would keep cancelling available during an outage, but without a queue (out of scope, see ADR-10) a lost retry leaves a cancelled student holding a bed, so I chose to fail. Moving the seam, for example giving Room Allocation a copy of registrations, was rejected because two copies of the same data would drift.
Consequences: ADR-2 held: the split was a cut, not a rewrite. The cost is that cancelling depends on both services being up, and creating rooms or assigning students depends on Trip Management answering within `TRIPS_TIMEOUT_S`.

## 7. One SQL Server database per service, changed only by numbered migrations
Date: 2026-11-22
Status: Decided
Context: The services must store data in SQL Server (serverless Azure SQL in the cloud), each in its own database reached with its own login, and the schema must evolve in place without losing rows. Assignment 1 created its SQLite schema on every boot.
Decision: Each service has its own database (`trips`, `rooms` locally; `<prefix>-<service>-db` on Azure) and a login that is a user only in that database. The schema lives in numbered SQL files in `services/<service>/migrations/`, applied at startup by a small runner in `db.py` that records each file in `schema_migrations` and commits the file and its record together. Cross-seam references (`rooms.trip_id`, `room_assignments.registration_id`) stay plain integers, as in ADR-3.
Alternatives considered: Alembic would add SQLAlchemy and a second way of describing tables, for a handful of plain SQL files; my runner is about forty lines I can explain line by line. One shared database with two schemas would have kept foreign keys across the seam, but the brief requires a database per service and it would couple their deployments.
Consequences: Integrity lost at the seam: no foreign key stops a room assignment pointing at a registration that was later cancelled, so Room Allocation checks the registration over HTTP before every assignment and Trip Management releases the bed when cancelling. If Trip Management's commit fails after the release succeeded, the bed is freed for a still-active student, which an organiser can reassign; the opposite (a cancelled student keeping a bed) cannot happen. Recovery plan for a bad migration: a failing file is rolled back with its record, the new revision does not start and the deploy's health check fails; a migration that ran but damaged data is fixed forward with a new migration, or the database is restored with Azure SQL point-in-time restore and `DATABASE_URL` pointed at the restored copy. Applied files are never edited.

## 8. Serverless hosting on Azure: Container Apps, serverless SQL and a static website
Date: 2026-11-22
Status: Decided
Context: The system must run on my Azure for Students credit, cost nothing while idle, and be deployed only by the pipeline after a one-time setup.
Decision: Both services run on Azure Container Apps (Consumption plan, minimum 0 and maximum 1 replica) in one environment, each database is a serverless General Purpose Gen5 database (0.5 to 1 vCore) on Azure SQL's free offer on one logical server, the UI is a Storage static website, images come from GHCR (public, so no registry password), and the pipeline signs in as a managed identity through OpenID Connect. `infra/azure-setup.sh` documents and runs the one-time setup.
Alternatives considered: App Service or a VM would answer instantly but bill every hour even when nobody uses the app. Azure Container Registry has a fixed monthly cost that GHCR does not. Provisioned Azure SQL would never pause, but costs money around the clock.
Consequences: Cost model: Container Apps bills per vCPU-second and request beyond a monthly free grant, the free-offer databases cost nothing up to their monthly vCore-seconds and pause after 60 idle minutes, and the static website and Log Analytics cost cents. Scale to zero means the first request after idle starts a container and may wake a paused database, which takes up to about a minute: `get_connection` retries with a growing wait (8 attempts at startup, 3 per request), Container Apps may answer 503 meanwhile, and the UI shows "starting up, please try again" instead of hanging. Running migrations at startup is only safe because there is never more than one replica. At 100x traffic I would keep at least one replica warm, raise the maximum and move migrations into a one-off Container Apps job that runs before the new revision, give the databases more vCores or a provisioned tier, and stop Room Allocation asking Trip Management on every write (cache registration status, or receive events).

## 9. Pipeline and tests: everything gated in CI, the seam tested against a stub
Date: 2026-11-22
Status: Decided
Context: Every push must be tested and every merge to main deployed with no manual steps, CI must never touch Azure SQL, and at least one test must cross the seam.
Decision: The `test` job runs ruff and pytest per service against a throwaway SQL Server container started in the job with a random, masked password, and fails below 70% coverage of the core modules; the `describe` job validates `system.yaml` against `system.schema.json` and both OpenAPI files; `images` builds both images and pushes them with the commit SHA only on main; `deploy` runs only on main after all of them, updates the Container Apps, uploads the UI with a generated `config.js`, and fails unless both `/health` endpoints answer 200 within several minutes. The cross-seam test (`test_cross_seam.py`) replaces Room Allocation with a real HTTP server started inside the test and checks that cancelling sends `POST /registrations/{id}/release`, and that the cancellation is rolled back when that server is down.
Alternatives considered: Running the cross-seam test against the full compose stack would also test Room Allocation's side, but needs both images, SQL Server and `db-init` running in CI and is slower and flakier; the stub keeps the real network call (URL, timeout, error handling) while staying fast and deterministic. Testing against SQLite in CI was rejected because the SQL dialect and locking differ from production.
Consequences: Room Allocation's own HTTP calls are tested with an in-memory fake at the adapter (`_get_json`), not over the network. Deliberately not tested: the browser JavaScript, the whole stack end to end in CI, load and cold starts, and Azure itself, which the post-deploy health check covers instead.

## 10. Do not add a message broker for the cancellation event
Date: 2026-11-22
Status: Decided
Context: Cancelling a registration is the one flow where Trip Management must tell Room Allocation something. Today it is a synchronous HTTP call, so cancelling fails while Room Allocation is down (ADR-6). Message brokers are out of scope for this assignment (§1c).
Decision: Keep the synchronous call and the rollback, and do not build a queue such as Azure Service Bus.
Alternatives considered: Trip Management could write a "registration cancelled" event to an outbox table in its own transaction and publish it to a queue; Room Allocation would consume it and release the bed, retrying until it succeeds. Cancelling would then work even while Room Allocation is down.
Consequences: Simpler system and no always-on or extra billed resource. It would be worth building once cancellations must keep working during Room Allocation outages, or once more services need the same event (for example sending a confirmation email), because then one event feeds several consumers instead of Trip Management calling each one.
