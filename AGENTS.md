# AGENTS.md

This repository is a Django + DRF API with strict tooling and a consistent response envelope.  
Agents (Codex, ChatGPT, other coding assistants) must follow these rules when adding or modifying endpoints, documentation, or schema.

---

## Prime directive

**Do not change runtime behavior unless explicitly asked.**  
Most “helpful refactors” are actually production bugs wearing a fake mustache.

---

## Non-negotiables

- **No moving/renaming** apps, modules, classes, serializers, or URL paths unless explicitly requested.
- **No URL shape changes**: keep API versioning and existing paths stable (`/api/v1/`).
- **No auth/permission changes** unless explicitly requested.
- **No throttling changes** unless explicitly requested.
- **No response-shape changes** unless explicitly requested.
- **No secrets** in code, commits, logs, tests, or docs. Use environment variables only.
- Keep changes **Ruff + MyPy + Bandit + tests + pre-commit** clean.

---

## Project conventions

### API base paths

- API endpoints live under: `/api/v1/`
- Schema/docs endpoints:
  - `/api/schema/`
  - `/api/docs/` (Swagger UI)
  - `/api/redoc/`

### Response envelope

Successful API responses are wrapped by:

- `config.api.responses.success_response(...)`

Expected envelope shape:

```json
{
  "success": 0,
  "message": "string",
  "data": "object|null"
}
```

Notes:

- Many endpoints return nested `data` payloads (dicts with serializers).
- **OpenAPI must document the envelope**, not only the request serializer.

If there is also an error wrapper (commonly `success: 1` or an `errors` key), do not guess.  
Inspect `config/api/responses.py` and existing endpoints and follow the established shape.

### App boundaries (do not cross the streams)

- Auth endpoints belong in the auth/accounts app (e.g. `accounts/`), not `api_keys/`.
- API key endpoints belong in `api_keys/`.
- Keep serializers in the same app as the views that use them (unless the repo already centralizes them).

### Security baseline

- Use ORM queries or parameterized queries only.
- Validate inputs with DRF serializers / validators (no ad-hoc `request.data[...]` parsing).
- Never log: passwords, JWTs, refresh tokens, API keys.
- Prefer `get_user_model()` over importing `User` directly unless the project intentionally hard-codes `User`.

---

## Documentation rules (docstrings)

All endpoints must be documented at **three levels**:

1. **Module docstring** (top of `views.py` / `viewsets.py`)

- What the module contains
- Authentication expectations
- Response envelope reminder

1. **Class docstring** (APIView / ViewSet)

- Purpose
- Auth / permissions
- Throttle scope (if used)
- Request serializer (if any)
- Response `data` payload shape in plain English

1. **Method docstring** (`get/post/put/patch/delete`)

- Inputs (body/query params)
- Outputs (envelope + important fields)
- Side effects (creates/updates/revokes/etc.)

Docstrings must describe reality. If behavior is unclear, **read the code and tests** first.

---

## OpenAPI rules (drf-spectacular)

This repo uses `drf-spectacular`. Document endpoints so Swagger is never “empty.”

### Request documentation

- For `POST/PUT/PATCH`: `@extend_schema(request=<Serializer>)` must match the serializer that validates `request.data`.
- For `GET/DELETE`: **do not** set `request=...` (GET has no request body).

### Response documentation (envelope-aware)

If the endpoint returns `success_response(...)`, then OpenAPI responses must describe:

- `success: int`
- `message: str`
- `data: <shape>`

Use `drf_spectacular.utils.inline_serializer(...)` to document the envelope **without changing runtime code**.

#### Minimal envelope templates

### Envelope with a serializer as data

```python
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers

EnvelopeOf = lambda name, data_serializer: inline_serializer(
    name=name,
    fields={
        "success": serializers.IntegerField(),
        "message": serializers.CharField(),
        "data": data_serializer,
    },
)
```

**Envelope with `data: null`**

```python
NullEnvelope = inline_serializer(
    name="NullEnvelope",
    fields={
        "success": serializers.IntegerField(),
        "message": serializers.CharField(),
        "data": serializers.JSONField(allow_null=True),
    },
)
```

**Envelope with dict-like data**
Use nested `inline_serializer(...)` fields that match the actual dict keys you return.

### Status codes

- Match real behavior (`200`, `201`, `204`) and include common auth errors (`401`, `403`) if relevant.
- Do not guess validation error schemas; follow existing patterns or DRF defaults.

### Definition of done for docs

- Swagger UI shows:
  - request body fields (for write endpoints)
  - response schema (envelope + data)
- No endpoint shows “No parameters” or “No response body” unless that is truly correct.

---

## Adding a new endpoint (required checklist)

When adding any new endpoint, do **all** of this:

1) Add/confirm URL path under the correct app + `/api/v1/...`
2) Add serializer(s) to validate input
3) Add tests (at least happy-path + one failure path)
4) Add docstrings (module/class/method)
5) Add `@extend_schema(...)`:
   - correct request serializer (if write)
   - correct response envelope schema
6) Run:

```bash
ruff check .
ruff format .
mypy .
bandit -c pyproject.toml -r .
pytest  # or: python manage.py test
python manage.py spectacular --file schema.yml
```

---

## Tooling expectations

### Ruff / formatting

- Keep imports clean and minimal.
- Avoid E501 by wrapping long decorators and dict literals.

### MyPy

- Avoid `attr-defined` regressions:
  - Don’t import names that don’t exist in a module.
  - Keep auth code out of `api_keys/` and vice versa.
- When you must cast (e.g., serializer `.data`), do it narrowly and explain why.

### Bandit

- No hardcoded secrets.
- No insecure randomness for security purposes (use `secrets` where needed).
- Avoid risky subprocess usage.

---

## Migrations

- Do not generate migrations unless explicitly required by a model change.
- If you add a model field, create and apply migrations and update tests accordingly.

---

## “Do not guess” policy

If you are unsure about:

- response error shape
- authentication classes in use
- throttle rates/scopes
- schema components names

Then:

1) search the repo for the established pattern
2) follow it exactly
3) document what you found via docstrings and `extend_schema`

---

## Quick example pattern (APIView + envelope docs)

```python
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.request import Request

from config.api.responses import success_response
from .serializers import ThingCreateSerializer, ThingSerializer

ThingEnvelope = inline_serializer(
    name="ThingEnvelope",
    fields={
        "success": serializers.IntegerField(),
        "message": serializers.CharField(),
        "data": ThingSerializer(),
    },
)

class ThingCreateView(APIView):
    """Create a Thing.

    Auth: IsAuthenticated
    Throttle: thing_create
    Response: envelope with `data` = ThingSerializer output.
    """

    @extend_schema(request=ThingCreateSerializer, responses={201: ThingEnvelope})
    def post(self, request: Request) -> Response:
        """Validate input, create a Thing, return envelope."""
        ser = ThingCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        thing = ser.save()
        return success_response(ThingSerializer(thing).data, status_code=status.HTTP_201_CREATED)
```

(Adjust to the repo’s actual patterns; the point is: **envelope is documented, behavior unchanged**.)

---

## If something breaks

- Prefer the smallest patch that restores correctness.
- Explain why it broke (imports, app boundaries, missing serializers, wrong schema annotations).
- Do not “solve” by moving code across apps or renaming things unless explicitly asked.
