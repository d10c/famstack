"""The DNS provider token: stored once, checked on every start, never shown.

With `[core] dns_provider` set, the infra stacklet's Caddy obtains its
certificates through that provider's API, which needs a token. It lives in
the secret store, never in stack.toml, and `stack infra dns-token` is the
one way in, for the first run and for every rotation after it. `stack up
infra` refuses to start a proxy that would fail to get certificates, and
says how to fix it.

The tests drive the real infra stacklet: its CLI command through
`Stack.run_cli_command`, the same path as `stack infra dns-token`, and its
start hook the way the framework calls it.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "lib"))

from stack import Stack  # noqa: E402
from stack.hooks import StackContext  # noqa: E402

TOKEN = "hk_test_0123456789abcdefghijklmnopqrstuvwxyz"


@pytest.fixture
def stack(tmp_path):
    """The repo's stacklets over a throwaway instance."""
    def _make(dns_provider: str = "hetzner") -> Stack:
        (tmp_path / "stack.toml").write_text(
            '[core]\ndomain = "home.example.family"\n'
            f'dns_provider = "{dns_provider}"\n'
            f'extension_dirs = ["{tmp_path / "ext"}"]\n')
        (tmp_path / ".stack").mkdir(exist_ok=True)
        return Stack(root=REPO, data=tmp_path / "data", instance_dir=tmp_path)
    return _make


def _dns_token(stck: Stack, stdin: str, monkeypatch) -> dict:
    """`stack infra dns-token` with the token piped in, as a script would."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    result = stck.run_cli_command("infra", "dns-token")
    assert result is not None
    return result


def _start(stck: Stack) -> None:
    path = REPO / "stacklets" / "infra" / "hooks" / "on_start.py"
    spec = importlib.util.spec_from_file_location("infra_on_start", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(StackContext(stck, "infra", {}))


# ── stack infra dns-token ─────────────────────────────────────────────────


def test_the_token_is_kept_in_the_secret_store(stack, monkeypatch):
    stck = stack()
    _dns_token(stck, TOKEN + "\n", monkeypatch)
    assert stck.secrets.get("infra", "DNS_API_TOKEN") == TOKEN


def test_the_token_is_never_echoed(stack, monkeypatch):
    """Command output ends up in terminals, logs and chat. Its length is
    enough to tell a pasted token from a truncated one."""
    result = _dns_token(stack(), TOKEN + "\n", monkeypatch)
    assert TOKEN not in repr(result)
    assert str(len(TOKEN)) in repr(result)


def test_a_new_token_replaces_the_old_one(stack, monkeypatch):
    stck = stack()
    _dns_token(stck, "old-token\n", monkeypatch)
    _dns_token(stck, TOKEN + "\n", monkeypatch)
    assert stck.secrets.get("infra", "DNS_API_TOKEN") == TOKEN


def test_an_empty_token_is_refused(stack, monkeypatch):
    stck = stack()
    _dns_token(stck, TOKEN + "\n", monkeypatch)
    result = _dns_token(stck, "\n", monkeypatch)
    assert "error" in result
    assert stck.secrets.get("infra", "DNS_API_TOKEN") == TOKEN


# ── stack up infra ────────────────────────────────────────────────────────


def test_start_needs_a_token_once_a_provider_is_set(stack):
    with pytest.raises(RuntimeError, match="stack infra dns-token"):
        _start(stack())


def test_start_goes_ahead_once_the_token_is_stored(stack, monkeypatch):
    stck = stack()
    _dns_token(stck, TOKEN + "\n", monkeypatch)
    _start(stck)


def test_plain_http_needs_no_token(stack):
    _start(stack(dns_provider=""))


def test_start_refuses_a_provider_the_image_has_no_plugin_for(stack, monkeypatch):
    stck = stack(dns_provider="unsupported")
    _dns_token(stck, TOKEN + "\n", monkeypatch)
    with pytest.raises(RuntimeError, match="unsupported"):
        _start(stck)


def test_route53_credentials_are_stored_without_echoing_them(stack, monkeypatch, capsys):
    stck = stack(dns_provider="route53")
    access_key = "AKIATESTEXAMPLE"
    secret_key = "fabricated-aws-secret"
    result = _dns_token(stck, f"{access_key}\n{secret_key}\n", monkeypatch)
    assert "error" not in result
    assert stck.secrets.get("infra", "AWS_ACCESS_KEY_ID") == access_key
    assert stck.secrets.get("infra", "AWS_SECRET_ACCESS_KEY") == secret_key
    output = repr(result) + repr(capsys.readouterr())
    assert access_key not in output
    assert secret_key not in output
    _start(stck)
    env = stck.env("infra")
    assert env["AWS_ACCESS_KEY_ID"] == access_key
    assert env["AWS_SECRET_ACCESS_KEY"] == secret_key
    assert env["AWS_REGION"] == "us-east-1"


def test_an_incomplete_route53_rotation_keeps_both_old_credentials(stack, monkeypatch):
    stck = stack(dns_provider="route53")
    _dns_token(stck, "old-access\nold-secret\n", monkeypatch)
    result = _dns_token(stck, "new-access\n", monkeypatch)
    assert "error" in result
    assert stck.secrets.get("infra", "AWS_ACCESS_KEY_ID") == "old-access"
    assert stck.secrets.get("infra", "AWS_SECRET_ACCESS_KEY") == "old-secret"


@pytest.mark.parametrize("missing", ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"])
def test_route53_needs_both_credentials_even_with_another_providers_token(stack, missing):
    stck = stack(dns_provider="route53")
    stck.secrets.set("infra", "DNS_API_TOKEN", TOKEN)
    other = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"} - {missing}
    for key in other:
        stck.secrets.set("infra", key, "fabricated")
    with pytest.raises(RuntimeError, match="stack infra dns-token"):
        _start(stck)


def test_proxy_settings_are_derived_from_config_without_changing_backend_access(stack, tmp_path):
    stck = stack()
    assert stck.env("infra")["PROXY_BIND_IP"] == "0.0.0.0"
    config = tmp_path / "stack.toml"
    config.write_text(config.read_text() +
                      '\n[infra]\nproxy_bind_ip = "100.64.0.10"\naws_region = "eu-west-1"\n')
    env = stck.env("infra")
    assert env["PROXY_BIND_IP"] == "100.64.0.10"
    assert env["PORT_BIND_IP"] == "127.0.0.1"
    assert env["AWS_REGION"] == "eu-west-1"


@pytest.mark.parametrize("configured", [False, True])
def test_route53_first_run_asks_only_if_aws_credentials_are_missing(stack, monkeypatch, configured):
    """A token left over from another provider must not suppress AWS setup."""
    import getpass

    stck = stack(dns_provider="route53")
    stck.secrets.set("infra", "DNS_API_TOKEN", TOKEN)
    if configured:
        stck.secrets.set("infra", "AWS_ACCESS_KEY_ID", "existing-access")
        stck.secrets.set("infra", "AWS_SECRET_ACCESS_KEY", "existing-secret")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    replies = iter(["new-access", "new-secret"])
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr(getpass, "getpass", answer)
    path = REPO / "stacklets" / "infra" / "hooks" / "on_configure.py"
    spec = importlib.util.spec_from_file_location("infra_on_configure", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(StackContext(stck, "infra", {}))
    assert len(prompts) == (0 if configured else 2)
    assert stck.secrets.get("infra", "AWS_SECRET_ACCESS_KEY") == (
        "existing-secret" if configured else "new-secret")
