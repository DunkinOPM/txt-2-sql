-- =============================================================================
-- Database Initialization Script for Clarification-Driven Text-to-SQL
-- NOTE: This script is executed by the PostgreSQL container ONLY when the data
-- directory is initialized for the first time.
-- For an existing database, see instructions in README.md / apply manually.
-- =============================================================================

-- 1. Create schemas
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS uploaded_data;

-- Ensure appuser owns the schemas
ALTER SCHEMA app OWNER TO appuser;
ALTER SCHEMA uploaded_data OWNER TO appuser;

-- 2. Revoke PUBLIC permissions on schemas to prevent privilege leakage
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
REVOKE ALL ON SCHEMA uploaded_data FROM PUBLIC;

-- 3. Create the least-privilege read-only role if not already created
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'readonly_user') THEN
        CREATE ROLE readonly_user WITH LOGIN PASSWORD 'readonly_dev_password'
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE;
    END IF;
END
$$;

-- 4. Database connect privilege
REVOKE ALL ON DATABASE text2sql FROM readonly_user;
GRANT CONNECT ON DATABASE text2sql TO readonly_user;

-- 5. Explicitly deny all access to schema 'app' (application metadata and query turns)
REVOKE ALL ON SCHEMA app FROM readonly_user;
REVOKE ALL ON ALL TABLES IN SCHEMA app FROM readonly_user;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA app FROM readonly_user;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM readonly_user;

ALTER DEFAULT PRIVILEGES FOR ROLE appuser IN SCHEMA app
    REVOKE ALL ON TABLES FROM readonly_user;
ALTER DEFAULT PRIVILEGES FOR ROLE appuser IN SCHEMA app
    REVOKE ALL ON SEQUENCES FROM readonly_user;
ALTER DEFAULT PRIVILEGES FOR ROLE appuser IN SCHEMA app
    REVOKE ALL ON FUNCTIONS FROM readonly_user;

-- 6. Grant read-only access to 'uploaded_data' schema
GRANT USAGE ON SCHEMA uploaded_data TO readonly_user;
GRANT SELECT ON ALL TABLES IN SCHEMA uploaded_data TO readonly_user;

-- Ensure future tables created by appuser in uploaded_data grant SELECT to readonly_user
ALTER DEFAULT PRIVILEGES FOR ROLE appuser IN SCHEMA uploaded_data
    GRANT SELECT ON TABLES TO readonly_user;

-- Explicitly ensure readonly_user cannot create, drop, or alter objects in uploaded_data
REVOKE CREATE ON SCHEMA uploaded_data FROM readonly_user;

