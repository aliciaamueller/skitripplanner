-- Room Allocation database on SQL Server.
-- The db-init job runs this on every `docker compose up`, so every
-- statement only creates what is missing and never drops anything.
-- Same tables and rules as services/room-allocation/schema.sql.
-- trip_id and registration_id belong to Trip Management, which has its
-- own database, so they have no foreign keys.

IF DB_ID('rooms') IS NULL
    CREATE DATABASE rooms;
GO

USE rooms;
GO

IF OBJECT_ID('dbo.rooms', 'U') IS NULL
CREATE TABLE dbo.rooms (
    id       INT IDENTITY PRIMARY KEY,
    trip_id  INT           NOT NULL,  -- trip ID from Trip Management, no FK
    name     NVARCHAR(100) NOT NULL,
    capacity INT           NOT NULL CHECK (capacity BETWEEN 1 AND 6),
    UNIQUE (trip_id, name)
);
GO

IF OBJECT_ID('dbo.room_assignments', 'U') IS NULL
CREATE TABLE dbo.room_assignments (
    id              INT IDENTITY PRIMARY KEY,
    room_id         INT NOT NULL REFERENCES dbo.rooms(id),
    registration_id INT NOT NULL UNIQUE  -- one room per person, no FK
);
GO

IF OBJECT_ID('dbo.roommate_preferences', 'U') IS NULL
CREATE TABLE dbo.roommate_preferences (
    id                        INT IDENTITY PRIMARY KEY,
    trip_id                   INT NOT NULL,  -- trip ID, no FK
    registration_id           INT NOT NULL,  -- who is asking, no FK
    preferred_registration_id INT NOT NULL,  -- who they want, no FK
    CHECK (registration_id <> preferred_registration_id),
    UNIQUE (registration_id, preferred_registration_id)
);
GO
