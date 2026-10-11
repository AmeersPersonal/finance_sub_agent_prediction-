-- Email/password accounts for the frontend's sign-up and sign-in forms
-- (POST /signup, POST /login; api/accounts.py). Signing in creates the same
-- session as Google sign-in, so /oauth/me, preferences and forecast quotas work
-- for both. Only a salted scrypt hash of each password is stored (oauth/passwords.py).
CREATE TABLE user_accounts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email TEXT NOT NULL UNIQUE CHECK (email = lower(email) AND length(email) BETWEEN 3 AND 254),
    password_hash TEXT NOT NULL CHECK (password_hash LIKE 'scrypt$%'),
    first_name TEXT NOT NULL CHECK (length(trim(first_name)) BETWEEN 1 AND 100),
    last_name TEXT NOT NULL CHECK (length(trim(last_name)) BETWEEN 1 AND 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
