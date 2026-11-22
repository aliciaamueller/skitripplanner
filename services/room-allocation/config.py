"""Room Allocation settings, read from environment variables with defaults."""

import os

# Port the web server listens on.
PORT = int(os.environ.get("PORT", "8000"))

# Connection string of this service's own SQL Server database, e.g.
# mssql://rooms_app:<password>@sqlserver:1433/rooms. It holds a password, so it
# has no default: compose sets it locally, the pipeline on Azure.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Base URL of the Trip Management service. Room Allocation asks it about
# trips and registrations over HTTP instead of reading its tables.
TRIPS_URL = os.environ.get("TRIPS_URL", "http://trip-management:8000")
