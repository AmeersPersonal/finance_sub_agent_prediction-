# Deploying to AWS (Lambda + CloudFront), built with SAM

`template.yaml` (repo root) describes the whole stack; `deploy.ps1`
build and ship it.

```
Browser ──► CloudFront ──► /*      S3 bucket          (the Vite build)
                      └──► /api/*  Lambda Function URL (FastAPI container image)
                                       │
                                       ├── PostgreSQL (your Tiger Cloud service, via DATABASE_URL)
                                       └── itself, asynchronously: the forecast worker
```

The browser only ever talks to the CloudFront domain, so the sign-in cookie stays
same-origin and the frontend needs no change (it already calls `/api/...`).

## Prerequisites

| Tool | Why |
|---|---|
| AWS CLI, with working credentials (`aws sts get-caller-identity`) | S3 upload, CloudFront, stack outputs |
| AWS SAM CLI (`winget install Amazon.SAM-CLI`, or the [installer](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)) | `sam build` / `sam deploy` |
| Docker, running | SAM builds the Lambda container image with it |
| Node.js 20+ | the frontend build |
| Python 3.12 (the `backend/.venv` works) | only for `-RunMigrations` |

## First deploy

PowerShell, from the repo root:

```powershell
.\deployws\deploy.ps1 -RunMigrations
```

(Only PowerShell is supported; on Linux/macOS use `pwsh`.)

The script:

1. checks the tools and your AWS credentials;
2. loads settings from `backend\.env` (or `-EnvFile`), with same-named environment
   variables winning, and asks for `DATABASE_URL` / `GEMINI_API_KEY` if missing.
   Values go to the function's environment and are never printed;
3. **ships the Snowflake key**: `SNOWFLAKE_PRIVATE_KEY_FILE` is a path on your machine,
   so the script reads that file and passes its contents. The function writes it to
   `/tmp` at run time and points `SNOWFLAKE_PRIVATE_KEY_FILE` there
   (`snowflake_rag/connection.py`). It stops if `RAG_BACKEND=snowflake` and the file
   isn't found;
4. gets a TLS certificate for `marketmoves.nyc` (see below);
5. runs `sam build` and `sam deploy`, applies migrations (010 adds the
   `prediction_jobs` table the Lambda needs), builds the frontend, uploads it and
   invalidates CloudFront.

### The domain, `marketmoves.nyc`

`-DomainName` defaults to `marketmoves.nyc` (`-DomainName ''` skips it). CloudFront
needs the certificate in `us-east-1`, so the script requests one there with DNS
validation.

- **DNS in Route 53:** the script adds the validation record, waits, and the stack
  creates the A/AAAA alias records. Nothing else to do.
- **DNS elsewhere (the registrar):** the script prints a CNAME to add and exits
  (code 2). Add it, rerun, and after the deploy point `marketmoves.nyc` at the printed
  CloudFront domain (an ALIAS/ANAME record for an apex name, or move the zone to
  Route 53).

With a domain set, the OAuth redirect URI is known up front:
`https://marketmoves.nyc/api/oauth/callback`. Add it once to the Google OAuth client;
no second deploy is needed.

## Later deploys

```powershell
.\deploy\aws\deploy.ps1                 # backend + frontend
.\deploy\aws\deploy.ps1 -SkipFrontend   # API only
.\deploy\aws\deploy.ps1 -SkipBackend    # frontend only (reads the stack outputs)
```

Add `-RunMigrations` after pulling a new migration. Change a value in `backend\.env` and
rerun to push it to the function. On a shared database, re-run
`backend/src/database/roles.sql` afterwards (`database/docs/retention-and-access.md`).

## Things to know

- **Database network access.** Lambda has no fixed outbound IP, so a database with an
  IP allow list (the team's Tiger Cloud service) must accept AWS addresses. For a
  hackathon, allow `0.0.0.0/0` and rely on TLS + the password. To lock it down, put
  the function in a VPC with a NAT gateway and an Elastic IP and allow-list that IP
  (about $30+/month); `template.yaml` does not do that yet. Campus Wi-Fi still blocks
  PostgreSQL from your laptop (`AGENTS.md`), which matters for `-RunMigrations`.
- **Forecast jobs.** The in-process job store can't work on Lambda (an instance is
  frozen after each response). With `JOBS_BACKEND=lambda`, `POST /prediction-jobs`
  stores a row in `prediction_jobs` and invokes the same function asynchronously; that
  invocation (a signed event, `POST /internal/lambda-events`) runs the forecast and
  writes the result. The response shape is unchanged. See `backend/src/api/lambda_jobs.py`.
- **Per-instance state.** The rate limit and score cache are in memory, so each Lambda
  instance counts separately. Forecast quota is therefore approximate under load.
- **Sessions** are stored in PostgreSQL (`OAUTH_SESSION_STORE=database`).
- **Function URL is public** (`AuthType: NONE`); the app enforces sign-in, and the
  worker route refuses any event without a valid HMAC signature.
- **Secrets** are stored as Lambda environment variables (encrypted at rest, visible
  to anyone with `lambda:GetFunctionConfiguration`). Move them to Secrets Manager if
  more people get access to the account.
- **Cost.** At hackathon volumes: pennies for Lambda/S3/CloudFront, plus the ECR image
  (~0.3 GB). Gemini usage is the real cost driver.

## A database with an IP allow list (Tiger Cloud)

Lambda has no fixed outbound IP, and Tiger Cloud accepts only /16 to /32 entries, so
allow-listing "AWS" isn't possible. Deploy with a static outbound IP instead:

```powershell
.\deploy\aws\deploy.ps1 -SkipFrontend -DomainName '' -StaticIp
```

This puts the function in a VPC (two private subnets) whose only route out is a NAT
gateway with one Elastic IP. The script prints `Outbound IP: x.x.x.x/32`; add exactly
that to the Tiger Cloud allow list, then check `<function url>/health`.

Cost: the NAT gateway is about $33/month plus data while the stack exists
(`sam delete` removes it and releases the IP). Without `-StaticIp` none of this is created.
The deploy user also needs the EC2 actions in `deploy-policy.json` (`VpcForStaticEgress`).

## Tear down

```powershell
aws s3 rm s3://<SiteBucketName output> --recursive    # the bucket must be empty
sam delete --stack-name market-moves
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Docker is installed but not running` | Start Docker Desktop. |
| `/api/health` returns 503 | `DATABASE_URL` wrong, migrations not applied, or the database's allow list blocks AWS. Check the function's CloudWatch log group `/aws/lambda/market-moves-api`. |
| Forecast stays `queued` | The worker invocation failed: check the log for `/internal/lambda-events`; confirm `JOB_SIGNING_KEY` is set and migration 010 is applied. |
| Sign-in loops back to the sign-in page | `OAuthRedirectUri` doesn't match the Google client's authorised URI (it must be https://marketmoves.nyc/api/oauth/callback). |
| `/Dashboard` shows an old build | CloudFront cache: the script invalidates `/*`; wait a minute and hard-refresh. |
