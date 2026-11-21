-- Trip Management database on SQL Server.
-- The db-init job runs this on every `docker compose up`, so every
-- statement only creates what is missing and never drops anything.
-- Same tables and rules as services/trip-management/schema.sql.

-- sqlcmd turns this off by default, but SQL Server needs it on to
-- create the filtered index at the end of this file.
SET QUOTED_IDENTIFIER ON;
GO

IF DB_ID('trips') IS NULL
    CREATE DATABASE trips;
GO

USE trips;
GO

IF OBJECT_ID('dbo.trips', 'U') IS NULL
CREATE TABLE dbo.trips (
    id          INT IDENTITY PRIMARY KEY,
    name        NVARCHAR(200) NOT NULL,
    destination NVARCHAR(200) NOT NULL,
    start_date  DATE          NOT NULL,
    end_date    DATE          NOT NULL,
    capacity    INT           NOT NULL CHECK (capacity > 0)
);
GO

-- status: pending_payment = place reserved until payment_deadline,
--         confirmed = paid, waitlisted = no free place yet,
--         cancelled = cancelled by the student or the deadline passed.
-- Rows are never deleted, so cancelled history is kept.
-- The default collation is case-insensitive, so email comparisons
-- ignore case like COLLATE NOCASE does in SQLite.
IF OBJECT_ID('dbo.registrations', 'U') IS NULL
CREATE TABLE dbo.registrations (
    id               INT IDENTITY PRIMARY KEY,
    trip_id          INT           NOT NULL REFERENCES dbo.trips(id),
    name             NVARCHAR(200) NOT NULL,
    email            NVARCHAR(320) NOT NULL,
    status           VARCHAR(20)   NOT NULL
        CHECK (status IN ('pending_payment', 'confirmed', 'waitlisted', 'cancelled')),
    registered_at    DATETIME2     NOT NULL,
    payment_deadline DATETIME2     NULL
);
GO

-- One active registration per email per trip.
-- Cancelled rows are left out, so a cancelled person can register again.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_registrations_active_email')
CREATE UNIQUE INDEX idx_registrations_active_email
    ON dbo.registrations (trip_id, email)
    WHERE status IN ('pending_payment', 'confirmed', 'waitlisted');
GO
