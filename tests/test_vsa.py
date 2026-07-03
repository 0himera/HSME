import pytest
import numpy as np
from backend.core.vsa import BipolarVSA

def test_vector_generation():
    vsa = BipolarVSA(dim=1000)
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
