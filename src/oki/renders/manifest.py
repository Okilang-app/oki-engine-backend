import hashlib
import json
from typing import Any
from uuid import UUID


class RenderManifest:
    """Deterministic manifest for render duplicate prevention."""

    @staticmethod
    def canonical_hash(
        *,
        job_id: UUID,
        inputs: dict[str, Any],
        output_spec: dict[str, Any],
    ) -> str:
        """Produce a deterministic SHA-256 hash of render inputs.

        Keys are sorted, UUIDs are stringified, and the JSON representation
        is canonical (no whitespace, sorted keys) to ensure cross-run
        stability.
        """
        payload = {
            "job_id": str(job_id),
            "inputs": _canonical_value(inputs),
            "output_spec": _canonical_value(output_spec),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canonical_value(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_canonical_value(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    return value
