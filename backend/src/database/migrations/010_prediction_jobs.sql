-- Forecast jobs that survive between API instances (api/lambda_jobs.py), for
-- hosting where a request's background task can't outlive its response (AWS
-- Lambda, JOBS_BACKEND=lambda). POST /prediction-jobs inserts a queued row and
-- starts a worker; GET /prediction-jobs/{id} reads it. The default in-process
-- JobStore (api/state.py) doesn't use this table. `owner` is the caller key
-- ("user:<sub>"); `result` is the stored forecast as JSON.
CREATE TABLE prediction_jobs (
    id TEXT PRIMARY KEY CHECK (length(id) = 32),
    owner TEXT NOT NULL CHECK (length(owner) BETWEEN 1 AND 300),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    result JSONB,
    error JSONB
);

CREATE INDEX prediction_jobs_finished_idx ON prediction_jobs (finished_at);
