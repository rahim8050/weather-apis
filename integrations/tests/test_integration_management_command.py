from __future__ import annotations

import base64
import io
import json
import uuid
from unittest.mock import patch

from django.core.management import call_command


def test_generate_hmac_client_command_outputs_values() -> None:
    fake_uuid = uuid.UUID("00000000-0000-0000-0000-000000000000")
    fake_secret = b"\x01" * 32
    secret_b64 = base64.b64encode(fake_secret).decode("ascii")
    env_json = json.dumps({str(fake_uuid): secret_b64})
    command_path = (
        "integrations.management.commands.integrations_generate_hmac_client"
    )

    with (
        patch(
            f"{command_path}.uuid.uuid4",
            return_value=fake_uuid,
        ),
        patch(
            f"{command_path}.secrets.token_bytes",
            return_value=fake_secret,
        ),
    ):
        out = io.StringIO()
        call_command("integrations_generate_hmac_client", stdout=out)

    output = out.getvalue().strip().splitlines()
    assert output[0] == f"CLIENT_ID={fake_uuid}"
    assert output[1] == f"SECRET_B64={secret_b64}"
    assert output[2] == f"INTEGRATION_HMAC_CLIENTS_JSON='{env_json}'"
    assert output[3] == "Store the secret securely; it is shown only once."
