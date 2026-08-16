import hashlib
import json


def compute_canonical_hash(data: dict) -> str:
    """Return a SHA-256 hex digest of *data* serialized as sorted JSON."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def material_change_invalidates(previous_hash: str, current_data: dict) -> bool:
    """Return True if *current_data* differs canonically from *previous_hash*."""
    return compute_canonical_hash(current_data) != previous_hash
