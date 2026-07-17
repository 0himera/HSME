import threading

import numpy as np
import pytest

from backend.core.vsa import BipolarVSA


def test_vector_generation():
    vsa = BipolarVSA(dim=1000, seed=42)
    v = vsa.generate_vector()
    assert v.shape == (1000,)
    # Check that all elements are 1 or -1
    assert np.all((v == 1) | (v == -1))

    # Check that it is pseudo-random (roughly 50/50 split)
    mean_val = np.mean(v)
    assert -0.1 < mean_val < 0.1


def test_binding_properties():
    vsa = BipolarVSA(dim=10000, seed=42)
    a = vsa.generate_vector()
    b = vsa.generate_vector()

    # Bind
    c = vsa.bind(a, b)
    assert c.shape == (10000,)
    assert np.all((c == 1) | (c == -1))

    # Reversibility: bind(c, b) should equal a
    a_recovered = vsa.bind(c, b)
    assert np.array_equal(a, a_recovered)

    # Similarity with unrelated vectors should be near 0
    d = vsa.generate_vector()
    assert abs(vsa.similarity(a, b)) < 0.05
    assert abs(vsa.similarity(c, a)) < 0.05

    # Similarity of vector with itself should be 1.0
    assert pytest.approx(vsa.similarity(a, a)) == 1.0


def test_bundling_properties():
    vsa = BipolarVSA(dim=10000, seed=42)
    a = vsa.generate_vector()
    b = vsa.generate_vector()
    c = vsa.generate_vector()

    # Bundle
    bundled = vsa.bundle([a, b, c])
    assert bundled.shape == (10000,)
    assert np.all((bundled == 1) | (bundled == -1))

    # Similarity of bundled vector with its constituents should be high (> 0)
    # Theoretically, for 3 vectors in the bundle, similarity should be around 0.5
    sim_a = vsa.similarity(bundled, a)
    sim_b = vsa.similarity(bundled, b)
    sim_c = vsa.similarity(bundled, c)

    assert sim_a > 0.3
    assert sim_b > 0.3
    assert sim_c > 0.3

    # Similarity with a non-constituent vector should be near 0
    d = vsa.generate_vector()
    assert abs(vsa.similarity(bundled, d)) < 0.05


def test_instance_rng_is_deterministic():
    """Same seed => same generated sequence across separate instances."""
    vsa_a = BipolarVSA(dim=1000, seed=123)
    vsa_b = BipolarVSA(dim=1000, seed=123)

    seq_a = [vsa_a.generate_vector() for _ in range(5)]
    seq_b = [vsa_b.generate_vector() for _ in range(5)]

    for va, vb in zip(seq_a, seq_b):
        assert np.array_equal(va, vb)


def test_instance_rng_does_not_mutate_global_numpy_state():
    """Creating a seeded VSA must not reset another instance's sequence or global RNG."""
    np.random.seed(999)
    before = np.random.randint(0, 1000, size=8)

    # Advance a separate instance; must not touch global np.random state
    other = BipolarVSA(dim=500, seed=1)
    _ = [other.generate_vector() for _ in range(10)]

    after = np.random.randint(0, 1000, size=8)

    # Reset global to same seed and confirm the "before" sequence is reproducible
    # and that "after" continued from where "before" left off (no reseed by VSA).
    np.random.seed(999)
    expected_before = np.random.randint(0, 1000, size=8)
    expected_after = np.random.randint(0, 1000, size=8)
    assert np.array_equal(before, expected_before)
    assert np.array_equal(after, expected_after)


def test_instances_do_not_interfere_with_each_other():
    """Advancing one seeded VSA must not alter another instance's sequence."""
    vsa_a = BipolarVSA(dim=800, seed=42)
    vsa_b = BipolarVSA(dim=800, seed=42)

    # Advance A only
    _ = [vsa_a.generate_vector() for _ in range(3)]

    # Fresh instance with same seed should still match the original first vector of B
    vsa_fresh = BipolarVSA(dim=800, seed=42)
    assert np.array_equal(vsa_b.generate_vector(), vsa_fresh.generate_vector())


def test_weighted_bundling_prioritizes_heavy_vector():
    """A weight-2 binding should dominate an equal-weight majority of lighter vectors."""
    vsa = BipolarVSA(dim=10000, seed=7)
    heavy = vsa.generate_vector()
    light_a = vsa.generate_vector()
    light_b = vsa.generate_vector()

    unweighted = vsa.bundle([heavy, light_a, light_b])
    weighted = vsa.bundle([heavy, light_a, light_b], weights=[2, 1, 1])

    # Weighted bundle should be closer to the heavy vector than the unweighted one
    assert vsa.similarity(weighted, heavy) >= vsa.similarity(unweighted, heavy)
    assert vsa.similarity(weighted, heavy) > 0.3


def test_unweighted_bundle_is_backward_compatible():
    """weights=None must match explicit all-ones weights."""
    # Seed both VSAs identically and generate the same vectors, then bundle.
    vsa_a = BipolarVSA(dim=5000, seed=11)
    vsa_b = BipolarVSA(dim=5000, seed=11)
    vecs_a = [vsa_a.generate_vector() for _ in range(4)]
    vecs_b = [vsa_b.generate_vector() for _ in range(4)]

    bundled_none = vsa_a.bundle(vecs_a)
    bundled_ones = vsa_b.bundle(vecs_b, weights=[1, 1, 1, 1])
    assert np.array_equal(bundled_none, bundled_ones)


def test_bundle_tie_resolution_returns_bipolar():
    """Even under forced ties, bundle must return only +1/-1."""
    vsa = BipolarVSA(dim=100, seed=3)
    a = np.ones(100, dtype=np.int8)
    b = -np.ones(100, dtype=np.int8)

    # Unweighted: a + b = 0 everywhere → all ties
    unweighted = vsa.bundle([a, b])
    assert np.all((unweighted == 1) | (unweighted == -1))

    # Weighted with equal opposing weight still ties
    weighted = vsa.bundle([a, b], weights=[2, 2])
    assert np.all((weighted == 1) | (weighted == -1))


def test_bundle_rejects_mismatched_weights():
    vsa = BipolarVSA(dim=100, seed=1)
    a = vsa.generate_vector()
    b = vsa.generate_vector()
    with pytest.raises(ValueError, match="weights length"):
        vsa.bundle([a, b], weights=[1])


def test_concurrent_generate_vector_orthogonality_smoke():
    """Multiple VSA instances generating in parallel stay roughly orthogonal."""
    dim = 10000
    n_instances = 8
    results: list[np.ndarray | None] = [None] * n_instances
    errors: list[BaseException] = []

    def worker(idx: int, seed: int) -> None:
        try:
            vsa = BipolarVSA(dim=dim, seed=seed)
            results[idx] = vsa.generate_vector()
        except BaseException as exc:  # noqa: BLE001 — surface any thread failure
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(i, 1000 + i))
        for i in range(n_instances)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert all(v is not None for v in results)

    vsa = BipolarVSA(dim=dim, seed=0)
    for i in range(n_instances):
        for j in range(i + 1, n_instances):
            sim = abs(vsa.similarity(results[i], results[j]))
            # Random bipolar vectors of dim=10k should be near-orthogonal
            assert sim < 0.08, f"vectors {i},{j} similarity={sim}"
