"""Trip Management settings, read from environment variables with defaults."""

import os

# Port the web server listens on.
PORT = int(os.environ.get("PORT", "8000"))

# Connection string of this service's own SQL Server database, e.g.
# mssql://trips_app:<password>@sqlserver:1433/trips. It holds a password, so it
# has no default: compose sets it locally, the pipeline on Azure.
DATABASE_URL = os.environ.get("DATABASE_URL")
