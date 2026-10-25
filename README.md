# Danjuma Bread

Django/Python web application for the Danjuma Bread multi-branch bakery. The original `danjuma_bread_pwa.html` remains as a prototype reference; the Django storefront is served from `/` and reads active products from the database.

## Current implementation

- Django 5.2 project with a custom email-based user model and role/branch fields.
- PostgreSQL-ready database configuration (`DATABASE_URL`); SQLite is used for local development by default.
- Initial models for branches, products, orders, order items, subscriptions, subscription items, and payment transactions.
- Django admin for trusted staff catalog and operations management.
- Responsive server-rendered bakery catalog and category filters.
- `/api/health/` database readiness endpoint.

Customer registration/sign-in, session basket, saved customer addresses, server-priced checkout, customer order history/reorder, branch-scoped staff order views, and audited order-status transitions are implemented. Checkout reserves inventory and creates an order in `PENDING`; it does not collect payment, and staff cannot mark an order paid. Once a trusted payment integration marks a delivery order paid, the application creates a timestamped signed dispatch token. Branch-assigned dispatchers can use the protected verification screen to confirm a dispatched order once; the token expires according to `QR_TOKEN_MAX_AGE` (default 24 hours).

The subscription job creates preparation orders independently of billing. Each due order is uniquely linked to a subscription/date, records a `PREPARATION_QUEUED` state and moves the next delivery date only after stock is reserved. The HTTP trigger at `/api/cron/subscriptions/` requires `Authorization: Bearer <CRON_SECRET>` and is CSRF-exempt only because it requires this secret; alternatively, use `python manage.py process_due_subscriptions`. The endpoint returns aggregate success/failure counts and does not expose subscription or customer details.

ALATPay/Paystack adapters and verified webhooks, recurring billing, actual QR image generation/scanning, customer address-book screens, and WhatsApp delivery/outbox retries are **not integrated yet**. A signed dispatch token is not itself a rendered QR image. Payment and subscription models are not evidence that payment collection or recurring billing is implemented.

## Local setup

1. Install Python 3.12 or newer and create an isolated environment:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. `.env` is git-ignored and already has local-only placeholders. For a fresh checkout, copy `.env.example` to `.env` and replace `SECRET_KEY` with a secure random value. The application reads environment variables from `.env` locally.

3. Required/configurable environment variables:

   - `SECRET_KEY`: Django signing/session secret (the Django equivalent of the requested `NEXTAUTH_SECRET`).
   - `DEBUG`: `True` only for local development; use `False` in deployed environments.
   - `ALLOWED_HOSTS`: comma-separated hostnames.
   - `CSRF_TRUSTED_ORIGINS`: comma-separated full origins, including scheme.
   - `DATABASE_URL`: local default is SQLite; use a managed PostgreSQL URL with the provider's pooled endpoint for serverless deployment.
   - `DELIVERY_SERVICE_FEE`: server-calculated delivery service fee; defaults to `0.00`.
   - `QR_TOKEN_MAX_AGE`: signed dispatch-token lifetime in seconds; defaults to `86400`.
   - `ALATPAY_API_KEY`, `ALATPAY_BUSINESS_ID`, `PAYSTACK_SECRET_KEY`: payment credentials, currently unused until gateway integration is implemented.
   - `CRON_SECRET`: required bearer secret for the subscription-job HTTP trigger; use a long random value.

   `SECRET_KEY` is required; the app refuses to start if it is missing. Do not commit real credentials. Configure deployed values through Vercel Project Settings; environment changes require a new deployment.

4. Create/apply migrations and an admin account:

   ```powershell
   python manage.py makemigrations bakery
   python manage.py migrate
   python manage.py createsuperuser
   ```

5. Run the application and tests:

   ```powershell
   python manage.py runserver
   python manage.py test
   ```

   Visit `http://127.0.0.1:8000/`, `http://127.0.0.1:8000/admin/`, and `http://127.0.0.1:8000/api/health/`.

## Vercel deployment notes

Vercel supports Django through its Python Function runtime and detects projects from `manage.py`; this project exposes `config.wsgi.application`. Vercel automatically runs `collectstatic` and serves files from the configured `STATIC_ROOT` through its CDN, so no custom `vercel.json` is needed for this basic WSGI app. Before deploying, set a strong `SECRET_KEY`, `DEBUG=False`, production `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and a managed PostgreSQL `DATABASE_URL` in Vercel. Prefer the provider's pooled/serverless database endpoint; Vercel Functions are request-driven, and local filesystem writes are not durable.

Django's `collectstatic` output is configured at `staticfiles/`. Confirm Vercel's Django build collects and serves it during an actual preview deployment. Database migrations should be run deliberately against staging/production—not implicitly during each request. Cron configuration is deferred until its authenticated, idempotent endpoint exists.
