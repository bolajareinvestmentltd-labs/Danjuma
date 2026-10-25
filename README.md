# Danjuma Bread

Django/Python web application for the Danjuma Bread multi-branch bakery. The original `danjuma_bread_pwa.html` remains as a prototype reference; the Django storefront is served from `/` and reads active products from the database.

## Current implementation

- Django 5.2 project with a custom email-based user model and role/branch fields.
- PostgreSQL-ready database configuration (`DATABASE_URL`); SQLite is used for local development by default.
- Initial models for branches, products, orders, order items, subscriptions, subscription items, and payment transactions.
- Django admin for trusted staff catalog and operations management.
- Responsive server-rendered bakery catalog and category filters.
- `/api/health/` database readiness endpoint.

Payment gateway calls, verified webhooks, customer checkout, QR dispatch verification, cron subscription execution, customer authentication screens, and WhatsApp delivery are **not integrated yet**. The models are groundwork, not evidence of completed payment or order fulfillment.

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
   - `ALATPAY_API_KEY`, `ALATPAY_BUSINESS_ID`, `PAYSTACK_SECRET_KEY`: payment credentials, currently unused until gateway integration is implemented.
   - `CRON_SECRET`: secret for a future scheduled endpoint, currently unused.

   Do not commit real credentials. Configure deployed values through Vercel Project Settings; environment changes require a new deployment.

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

Vercel supports Django through its Python Function runtime. This project has a conventional `manage.py` and WSGI entry point at `config.wsgi.application`. Before deploying, set a strong `SECRET_KEY`, `DEBUG=False`, production `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and a managed PostgreSQL `DATABASE_URL` in Vercel. Prefer the provider's pooled/serverless database endpoint; Vercel Functions are request-driven, and local filesystem writes are not durable.

Django's `collectstatic` output is configured at `staticfiles/`. Confirm Vercel's Django build collects and serves it during an actual preview deployment. Database migrations should be run deliberately against staging/production—not implicitly during each request. Cron configuration is deferred until its authenticated, idempotent endpoint exists.
