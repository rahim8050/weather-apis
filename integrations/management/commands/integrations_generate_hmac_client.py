from __future__ import annotations

import base64
import json
import secrets
import uuid

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Generate an integration HMAC client id + secret for "
        "INTEGRATION_HMAC_CLIENTS_JSON."
    )

    def handle(self, *args: object, **options: object) -> None:
        client_id = str(uuid.uuid4())
        secret_bytes = secrets.token_bytes(32)
        secret_b64 = base64.b64encode(secret_bytes).decode("ascii")
        env_json = json.dumps({client_id: secret_b64})

        self.stdout.write(f"CLIENT_ID={client_id}")
        self.stdout.write(f"SECRET_B64={secret_b64}")
        self.stdout.write(f"INTEGRATION_HMAC_CLIENTS_JSON='{env_json}'")
        self.stdout.write("Store the secret securely; it is shown only once.")
