from uuid import UUID

from oki.renders.manifest import RenderManifest


def test_canonical_hash_is_deterministic() -> None:
    job_id = UUID("12345678-1234-7123-8123-123456789abc")
    inputs = {"edl": {"cut": "0-10"}, "audio": {"track": 1}}
    output_spec = {"format": "mp4", "resolution": "1920x1080"}

    hash1 = RenderManifest.canonical_hash(
        job_id=job_id, inputs=inputs, output_spec=output_spec
    )
    hash2 = RenderManifest.canonical_hash(
        job_id=job_id, inputs=inputs, output_spec=output_spec
    )
    assert hash1 == hash2
    assert len(hash1) == 64


def test_canonical_hash_differs_with_different_inputs() -> None:
    job_id = UUID("12345678-1234-7123-8123-123456789abc")
    base_inputs = {"edl": {"cut": "0-10"}}
    output_spec = {"format": "mp4"}

    hash1 = RenderManifest.canonical_hash(
        job_id=job_id, inputs=base_inputs, output_spec=output_spec
    )
    hash2 = RenderManifest.canonical_hash(
        job_id=job_id, inputs={"edl": {"cut": "0-11"}}, output_spec=output_spec
    )
    assert hash1 != hash2


def test_canonical_hash_stringifies_nested_uuids() -> None:
    nested_uuid = UUID("abcdef12-3456-7123-8123-abcdef123456")
    job_id = UUID("12345678-1234-7123-8123-123456789abc")
    inputs = {"asset_id": nested_uuid, "data": [nested_uuid]}
    output_spec = {}

    result = RenderManifest.canonical_hash(
        job_id=job_id, inputs=inputs, output_spec=output_spec
    )
    assert isinstance(result, str)
    assert len(result) == 64


def test_canonical_hash_sorts_dict_keys() -> None:
    job_id = UUID("12345678-1234-7123-8123-123456789abc")
    inputs_a = {"z": 1, "a": 2}
    inputs_b = {"a": 2, "z": 1}
    output_spec = {}

    hash_a = RenderManifest.canonical_hash(
        job_id=job_id, inputs=inputs_a, output_spec=output_spec
    )
    hash_b = RenderManifest.canonical_hash(
        job_id=job_id, inputs=inputs_b, output_spec=output_spec
    )
    assert hash_a == hash_b
