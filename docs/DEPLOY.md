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
5. The first build took about 40 minutes, because it installs every dependency and trains the models. Render then shows the site's address.

## What to expect

- **It sleeps.** Render stops a free service after 15 minutes with no visitors. The next visitor waits about a minute for Render, plus the time the app takes to load on a very small CPU. Open it a few minutes before a demo.
- **Limits.** Neon's free plan has 1 GB of storage per project and 100 compute hours per month. The demo database is about 94 MB, and Neon also sleeps when idle.
- **Demo tickets age.** Open tickets pass their deadlines within about three days, and the 30-day dashboard view thins out over time. Run the seed against an emptied database to refresh it.
- **Anyone with the password can change the demo data.** It holds only synthetic data. Keep the password out of public pages and share it directly.
- **Anyone can create a User account.** New accounts can raise tickets and use the assistant, and see only their own tickets and public articles.
- **Creating an Admin account needs the access code.** Render generates `ADMIN_SIGNUP_CODE`, and you can read it on the service's Environment page. Keep it private, because it grants full control of the site.

## Verified and not verified

Deployed on 3 November 2026 at <https://incident-platform-ql4e.onrender.com>, using PostgreSQL 17 and pgvector 0.8.0 on Neon.

Verified on the live site in a browser: sign-in with secure cookies, the incident list, notification charts, the dashboard, ticket triage, cited answers, refusal of an off-topic question and the sign-up rules. The service stayed healthy after that AI work.

| Live timing, once awake | Time |
| --- | --- |
| First assistant answer, which loads the embedding model | 15 s |
| Later answers | 1 to 6 s |
| New ticket with AI triage | 3 s |

Verified locally with production settings and no Redis or Celery processes: all four scheduled jobs run and succeed.

Not measured on the live site:

- How long the first visit takes after the service has slept.
- Memory use, which Render shows in its dashboard. The 411 MB peak was measured on Windows.
- Scheduled jobs and alerts, which need Render's logs to confirm.
