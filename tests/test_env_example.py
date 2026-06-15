"""Guard: .env.example documents the full PDND configuration contract (ADR 0015).

The SDK's ``ClientAssertionSettings`` fails fast at startup unless all six
``PDND_PURPOSE_ID_*`` are present and a key source is set. This test keeps the
committed template from drifting away from that contract; the purpose-id set is
derived from the SDK's ``APIType`` enum, so a new API there fails this test until
the template is updated.
"""

from pathlib import Path

from anncsu.common.config import APIType

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def _declared_keys() -> set[str]:
    """The KEY names declared as ``KEY=value`` lines (comments/blank lines ignored)."""
    keys: set[str] = set()
    for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


def test_env_example_exists():
    assert ENV_EXAMPLE.is_file(), ".env.example should be committed at the repo root"


def test_env_example_declares_every_purpose_id():
    missing = {api.env_var_name for api in APIType} - _declared_keys()
    assert not missing, f".env.example is missing purpose ids: {sorted(missing)}"


def test_env_example_declares_the_required_assertion_fields():
    keys = _declared_keys()
    required = {"PDND_KID", "PDND_ISSUER", "PDND_SUBJECT", "PDND_AUDIENCE"}
    assert required <= keys, f".env.example is missing: {sorted(required - keys)}"
    # The SDK requires a key source; the template offers PDND_KEY_PATH.
    assert "PDND_KEY_PATH" in keys or "PDND_PRIVATE_KEY" in keys


def test_env_example_declares_the_modi_audit_context():
    # The ModI audit context (AUDIT_REST_02) is used by the write APIs. The
    # dedicated ModI signing key (PDND_MODI_KID / *_KEY_PATH) is optional — prod
    # only — so it is documented as a comment, not asserted here.
    keys = _declared_keys()
    required = {"PDND_MODI_USER_ID", "PDND_MODI_USER_LOCATION", "PDND_MODI_LOA"}
    assert required <= keys, f".env.example is missing ModI audit keys: {sorted(required - keys)}"
