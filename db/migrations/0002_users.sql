-- ============================================================================
-- 0002_users.sql — Users table, roles, session/CSRF store (Step 4, D-12/D-11)
--
-- Implements:
--   D-12  argon2-cffi password hashes stored as TEXT (OWASP floor verified in app)
--   D-11  per-session CSRF tokens stored here; signed cookies are itsdangerous
--   CK-12 two-role model: admin (write) vs accountant (read-only)
--
-- The users table is NOT one of the four sacred append-only ledger tables
-- (accounts/journal_entries/journal_lines/fiscal_periods).  Passwords and
-- role assignments change over time, so UPDATE is permitted on `users` —
-- but only on specific columns (password_hash, role, is_active), never on
-- the identity columns.  A trigger enforces column-level write restriction.
--
-- Session/CSRF tokens live in `user_sessions` (one row per active session).
-- Logout deletes the row; expiry is via a TTL column checked by the app.
-- ============================================================================

CREATE TABLE users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,                    -- argon2-cffi hash string
    role          TEXT NOT NULL
                  CHECK (role IN ('admin', 'accountant')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Column-level write restriction: only password_hash, role, is_active,
-- and updated_at may be UPDATEd.  This prevents privilege escalation via
-- username or id rewriting.
CREATE OR REPLACE FUNCTION guard_users_update() RETURNS trigger AS $$
BEGIN
    IF NEW.username IS DISTINCT FROM OLD.username THEN
        RAISE EXCEPTION 'users.username is immutable (create a new user instead)';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id THEN
        RAISE EXCEPTION 'users.id is immutable';
    END IF;
    IF NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'users.created_at is immutable';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_update_guard
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION guard_users_update();

-- Per-session CSRF token store (D-11 / trap 10).
CREATE TABLE user_sessions (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users (id),
    csrf_token   TEXT NOT NULL,                      -- per-session random token
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_user_sessions_user ON user_sessions (user_id);
CREATE INDEX idx_user_sessions_expires ON user_sessions (expires_at);

-- Grant the app role access (INSERT for login, SELECT for verify, DELETE for logout).
GRANT SELECT, INSERT, DELETE ON users, user_sessions TO ledger_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ledger_app;
-- ---------------------------------------------------------------------------
-- current_user_id() — returns the app-level user ID from session context.
--
-- The application sets `SET LOCAL app.user_id = <id>` at the start of each
-- transaction.  RLS policies and audit triggers call this function to
-- enforce per-user row isolation without a hardcoded user.
-- Returns NULL if not set (allows superuser / migration connections).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION current_user_id() RETURNS BIGINT AS $$
    SELECT NULLIF(current_setting('app.user_id', true), '')::BIGINT
$$ LANGUAGE SQL STABLE;
