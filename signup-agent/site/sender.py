"""Gives the demo site an address of its own and a key that can only send from it.

    python site/sender.py    # run.sh does this for you the first time

`run.sh` runs it the first time. It uses the agent's key (`PIDGEON_API_KEY`) to create
`noreply-demo-<random>@pidgeon.email`, mints a second key that can send from
that one address and do nothing else, and adds it to `.env` as
`SITE_PIDGEON_API_KEY`. The site never holds the agent's key, and the agent
never needs the site's.
"""

import json
import os
import secrets
import sys
from pathlib import Path

from pidgeon import AuthenticatedClient
from pidgeon.api.identities import identities_create
from pidgeon.api.keys import keys_create
from pidgeon.models import (
    Error,
    IdentitiesCreateBody,
    IdentitiesCreateBodyType,
    KeysCreateBody,
    KeysCreateBodyAccess,
)

ENV = Path(__file__).resolve().parent.parent / ".env"


def main() -> None:
    if os.environ.get("SITE_PIDGEON_API_KEY"):
        sys.exit("SITE_PIDGEON_API_KEY is already set.")

    client = AuthenticatedClient(
        base_url=os.environ.get("PIDGEON_BASE_URL", "https://pidgeon.ai/api/v1"),
        token=os.environ["PIDGEON_API_KEY"],
    )
    domain = os.environ.get("PIDGEON_DOMAIN", "pidgeon.email")

    address = identities_create.sync(
        client=client,
        body=IdentitiesCreateBody(
            address=f"noreply-demo-{secrets.token_hex(3)}@{domain}",
            display_name="Acme Demo",
            type_=IdentitiesCreateBodyType.AGENT,
        ),
    )
    if isinstance(address, Error):
        sys.exit(address.error.message)

    # `_detailed` for the raw body: pidgeon 1.14's typed answer leaves out the token.
    minted = keys_create.sync_detailed(
        client=client,
        body=KeysCreateBody(
            name="signup-agent demo site",
            identity_ids=[address.data.id],
            access=KeysCreateBodyAccess.SEND,
        ),
    )
    if isinstance(minted.parsed, Error):
        sys.exit(minted.parsed.error.message)

    # Returned once, here, and nowhere else.
    token = json.loads(minted.content)["data"]["token"]
    lines = [line for line in ENV.read_text().splitlines() if not line.startswith("SITE_PIDGEON_API_KEY=")]
    ENV.write_text("\n".join([*lines, f"SITE_PIDGEON_API_KEY={token}"]) + "\n")

    print(f"The site sends from {address.data.email}. Its key is in {ENV}.")


if __name__ == "__main__":
    main()
