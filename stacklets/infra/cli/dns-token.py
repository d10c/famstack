"""
stack infra dns-token: store the credentials of the DNS provider.

With `[core] dns_provider` set, Caddy obtains its certificates by writing
a TXT record through the provider's API. Credentials are kept in the secret
store (`.stack/secrets.toml`), never in stack.toml, and reach the Caddy
container on the next `stack up infra`.

In a terminal it asks for credentials without echoing them. Piped, it reads
one line per credential: a token for Hetzner/Cloudflare, or an access key ID
followed by a secret access key for Route53. Run it again to replace the
credentials, then `stack up infra`.

    stack infra dns-token
"""

HELP = "Store or replace the DNS provider credentials used for HTTPS"

import getpass
import sys
from pathlib import Path

from stack.caddy import DNS_CREDENTIALS
from stack.secrets import TomlSecretStore


# What each provider's Caddy plugin authenticates with. Hetzner's plugin
# talks to the Hetzner Cloud API, so a token from the older DNS Console
# does not work.
_TOKEN_KIND = {
    "hetzner": "a Hetzner Cloud API token with Read & Write access, created in "
               "the Console project that holds the zone (Security > API tokens)",
    "cloudflare": "a Cloudflare API token with Zone.Zone:Read and Zone.DNS:Edit "
                  "on the zone",
    "route53": "an AWS access key ID and secret access key with Route53 "
               "permissions for the zone (see stacklets/infra/README.md)",
}


def _read_credentials(provider: str) -> dict[str, str]:
    interactive = sys.stdin.isatty()
    if interactive and provider in _TOKEN_KIND:
        print(f"  {provider} needs {_TOKEN_KIND[provider]}.", file=sys.stderr)
    credentials = {}
    for name in DNS_CREDENTIALS.get(provider, ("DNS_API_TOKEN",)):
        value = (getpass.getpass(f"  ▸ {name} (input hidden): ")
                 if interactive else sys.stdin.readline())
        credentials[name] = value.strip()
    return credentials


def run(args, stacklet, config):
    provider = config["stack"].get("core", {}).get("dns_provider", "")
    credentials = _read_credentials(provider)
    if not all(credentials.values()):
        return {"error": "Missing credentials. The stored credentials, if any, are unchanged."}

    store = TomlSecretStore(Path(config["instance_dir"]) / ".stack" / "secrets.toml")
    for name, value in credentials.items():
        store.set(stacklet["id"], name, value)
    lengths = ", ".join(f"{name}: {len(value)} characters"
                        for name, value in credentials.items())
    return {
        "stored": f"DNS credentials ({lengths})",
        "next": "stack up infra",
    }
