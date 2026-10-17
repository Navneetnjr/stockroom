-- Runs once, the first time the Docker database starts.
-- The main "stockroom" database is created by POSTGRES_DB; this adds the test database.
CREATE DATABASE stockroom_test;
