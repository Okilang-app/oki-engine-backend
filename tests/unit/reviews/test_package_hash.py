from oki.reviews.versioning import compute_canonical_hash, material_change_invalidates


def test_compute_canonical_hash_deterministic() -> None:
    data = {"b": 2, "a": 1}
    h1 = compute_canonical_hash(data)
    h2 = compute_canonical_hash({"a": 1, "b": 2})
    assert h1 == h2
    assert len(h1) == 64


def test_compute_canonical_hash_different_data() -> None:
    h1 = compute_canonical_hash({"a": 1})
    h2 = compute_canonical_hash({"a": 2})
    assert h1 != h2


def test_material_change_invalidates_detects_change() -> None:
    original = {"title": "Original", "segments": [{"id": 1}]}
    h = compute_canonical_hash(original)
    assert material_change_invalidates(h, {"title": "Changed", "segments": [{"id": 1}]}) is True


def test_material_change_invalidates_unchanged() -> None:
    original = {"title": "Same", "segments": [{"id": 1}]}
    h = compute_canonical_hash(original)
    assert material_change_invalidates(h, {"title": "Same", "segments": [{"id": 1}]}) is False
