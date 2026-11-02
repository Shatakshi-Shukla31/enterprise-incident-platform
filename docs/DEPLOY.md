# Free hosting

This runs the demo at no cost on [Render](https://render.com) for the app and [Neon](https://neon.com) for the database. Prices and limits were checked on 2 November 2026 and can change.

The full deployment in `docker-compose.yml` needs about 750 MB or more, while a free server has 512 MB. So the root `Dockerfile` runs the website, API and scheduled jobs in one process, with no Redis or Celery worker. Measured in that mode on Windows, memory peaked at 411 MB.

| Part | Full deployment | Free hosting |
| --- | --- | --- |
| Website | nginx | Served by the API process |
| Background work | Celery worker and Redis | Runs inline in the request |
| Scheduled jobs | Celery beat | A thread in the API process |
| Rate limits | Shared in Redis | In memory |

## Steps

1. Create a [Neon](https://neon.com) project in the Singapore region and copy its connection string.
2. Create an empty GitHub repository and push this code.
3. Load the database once. This uses your local `.env` for `DEMO_PASSWORD` and takes several minutes. From `backend`, run this as one line, because a pasted block would answer the prompt with its own next line:

   ```powershell
   $env:DATABASE_URL = Read-Host "Paste the Neon connection string"; $env:DB_DISABLE_PREPARED_STATEMENTS = "true"; $env:SINGLE_PROCESS = "true"; python -m alembic upgrade head; python -m scripts.seed_demo
   ```

   Close that PowerShell window afterwards, so your local app keeps using its own database.

4. On [Render](https://render.com), choose **New**, then **Blueprint**, and select the repository. `render.yaml` sets everything except `DATABASE_URL`, which Render asks for. Paste the same connection string.
5. The first build takes several minutes, because it trains the models. Render then shows the site's address.

## What to expect

- **It sleeps.** Render stops a free service after 15 minutes with no visitors. The next visitor waits about a minute for Render, plus the time the app takes to load on a very small CPU. Open it a few minutes before a demo.
- **Limits.** Neon's free plan has 1 GB of storage per project and 100 compute hours per month. The demo database is about 94 MB, and Neon also sleeps when idle.
- **Demo tickets age.** Open tickets pass their deadlines within about three days, and the 30-day dashboard view thins out over time. Run the seed against an emptied database to refresh it.
- **Anyone with the password can change the demo data.** It holds only synthetic data. Keep the password out of public pages and share it directly.
- **Anyone can create a User account.** New accounts can raise tickets and use the assistant, and see only their own tickets and public articles.
- **Creating an Admin account needs the access code.** Render generates `ADMIN_SIGNUP_CODE`, and you can read it on the service's Environment page. Keep it private, because it grants full control of the site.

## Verified and not verified

Verified on a Windows machine with a throwaway database, using production settings, no Redis and no Celery processes: migrations, seeding, sign-in with secure cookies, ticket triage, the assistant, the dashboard and all four scheduled jobs.

Not verified until the first real deployment:

- The root `Dockerfile` has never been built, because Docker is not available on the development machine.
- Neon's connection pooler and pgvector were not tested. Local tests used PGlite.
- Memory use on Linux and speed on Render's 0.1 CPU were not measured.
