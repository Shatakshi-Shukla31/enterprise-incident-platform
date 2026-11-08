# Browser tests

Playwright tests that drive a real browser against a running instance: sign-in and sign-up rules, the read-only demo, risk explanations, notification charts, phone width and an automated accessibility scan. CI runs them on every push.

```powershell
npm.cmd ci
$env:E2E_BASE_URL = "http://localhost:8010"   # any running instance
$env:PW_CHANNEL = "msedge"                     # use the installed Edge, or run: npx.cmd playwright install chromium
$env:E2E_DEMO_PASSWORD = "..."                 # optional: the seeded DEMO_PASSWORD
$env:E2E_ADMIN_CODE = "..."                    # optional: the server's ADMIN_SIGNUP_CODE
npx.cmd playwright test
```

The tests create a few accounts with `e2e-...@example.com` addresses, so point them at a demo or throwaway database.
