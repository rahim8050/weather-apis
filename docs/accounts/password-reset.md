# Password reset (accounts)

Password reset is handled entirely within the accounts app via JWT-protected admin routes. The feature
covers request + confirm flows, ensuring tokens are one-time-use and the actual password change never
leaks secrets back to the client.

## Purpose & security
- Purpose: allow users to reset forgotten passwords while keeping the process stateless on the client.
- Security:
  - Tokens come from Django's `default_token_generator` and expire per `PASSWORD_RESET_TIMEOUT_DAYS`.
  - Tokens are single-use and tied to a specific user ID (`uidb64`), so replays are rejected with `"Invalid or expired reset link."`.
  - No secrets (passwords, tokens, API keys) are returned in responses.

## Endpoints
- `POST /api/v1/auth/password/reset/`
  - Request: `{"email": "user@example.com"}`
  - Response: `{"status": 0, "message": "If an account exists for this email, a reset link has been sent.", "data": null, "errors": null}`
  - Action: finds active user by email, builds `uid` and token, and sends a reset link to `FRONTEND_RESET_URL`.
  - No error when the email is missing or not associated with an account; this prevents user enumeration.

- `POST /api/v1/auth/password/reset/confirm/`
  - Request: `{"uid": "<uidb64>", "token": "<token>", "new_password": "StrongPass123!"}`
  - Success response: `{"status": 0, "message": "Password has been reset.", "data": null, "errors": null}`
  - Failure response: `{"status": 1, "message": "Invalid or expired reset link.", "data": null, "errors": {"token": ["Invalid or expired token."]}}`
  - Side effects: updates the user's password when the token is valid and the new password passes Django validators.

## Required settings / env vars
- `FRONTEND_RESET_URL` – base URL that receives `uid` + `token` in the password reset link.
- `DEFAULT_FROM_EMAIL`, `EMAIL_BACKEND`, and SMTP settings (`EMAIL_HOST`, `EMAIL_PORT`, etc.).
  The send_mail call is guarded by `fail_silently=True`, so missing SMTP configuration does not crash the API, but emails will not be delivered.
- `DJANGO_ENV`, `DJANGO_SECRET_KEY`, and DB-related settings remain required per the general README.

## Common errors & troubleshooting
- **Invalid/expired reset link**: token already used or `PASSWORD_RESET_TIMEOUT_DAYS` (Django default = 3) elapsed.
  - Remedy: request a new reset link and reissue a token; confirm the `uid` matches the emailed value.
- **Password validation failure**: new password fails Django validators (length, numeric, etc.).
  - The response returns `errors` describing the failing constraints.
- **Email delivery issues**: SMTP misconfiguration prevents link delivery; check `DEFAULT_FROM_EMAIL` and `EMAIL_BACKEND`.
  - Use local SMTP logs or `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` in dev.

## Sample JSON flows
1. Request reset:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/password/reset/ \
        -H "Content-Type: application/json" \
        -d '{"email": "alice@example.com"}'
   ```
2. Confirm reset:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/password/reset/confirm/ \
        -H "Content-Type: application/json" \
        -d '{"uid": "<uidb64>", "token": "<token>", "new_password": "StrongPass123!"}'
   ```

See `accounts/views.py` for the serializer fields that must be submitted.
