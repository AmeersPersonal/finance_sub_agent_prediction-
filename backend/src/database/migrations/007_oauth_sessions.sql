-- Shared OAuth login state, so several API worker processes see the same sign-ins
-- (OAUTH_SESSION_STORE=database; oauth/sessions.DatabaseStore). The default store
-- is process memory and doesn't touch these tables.
--
-- State values and session ids are bearer secrets: only their SHA-256 hashes are
-- stored, so reading these tables doesn't yield a usable cookie. The PKCE verifier
-- must be kept as-is for the token exchange; it lives 10 minutes and is deleted
-- on first use. Provider tokens are never stored anywhere.
CREATE TABLE oauth_pending_logins (
    state_hash TEXT PRIMARY KEY CHECK (length(state_hash) = 64),
    verifier TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX oauth_pending_logins_expiry_idx ON oauth_pending_logins (expires_at);

CREATE TABLE oauth_sessions (
    session_hash TEXT PRIMARY KEY CHECK (length(session_hash) = 64),
    user_profile JSONB NOT NULL CHECK (jsonb_typeof(user_profile) = 'object'),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX oauth_sessions_expiry_idx ON oauth_sessions (expires_at);
