import numpy as np

class BipolarVSA:
    def __init__(self, dim: int = 10000, seed: int = None):
        self.dim = dim
        if seed is not None:
            np.random.seed(seed)

    def generate_vector(self) -> np.ndarray:
        """Generates a random bipolar vector (+1 or -1) of dimension self.dim."""
        return np.random.choice([-1, 1], size=self.dim).astype(np.int8)

    def bind(self, v1: np.ndarray, v2: np.ndarray) -> np.ndarray:
        """Binds two bipolar vectors using element-wise multiplication.
        
        Binding is reversible: bind(bind(a, b), b) approximates a.
        """
        return (v1 * v2).astype(np.int8)

    def bundle(self, vectors: list[np.ndarray]) -> np.ndarray:
        """Bundles multiple bipolar vectors using majority vote.
        
        If the sum is 0 (tie), a random +1 or -1 is chosen.
        """
        if not vectors:
            raise ValueError("Cannot bundle an empty list of vectors.")
        if len(vectors) == 1:
            return vectors[0].copy()
            
        stacked = np.stack(vectors, axis=0)
        summed = np.sum(stacked, axis=0)
        
        # Majority vote
        bundled = np.sign(summed).astype(np.int8)
        
        # Handle ties (where sign is 0) by randomly assigning +1 or -1
        ties = (bundled == 0)
        if np.any(ties):
            random_choices = np.random.choice([-1, 1], size=np.sum(ties)).astype(np.int8)
            bundled[ties] = random_choices
            
        return bundled

    def similarity(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """Calculates the cosine similarity between two bipolar vectors.
        
        For bipolar vectors of the same dimension, this is equivalent to:
        (dot_product) / dim
        Returns a value between -1.0 and 1.0.
        """
        # Since v1 and v2 only contain -1 and 1, their norms are both sqrt(dim)
        # Cosine similarity = dot(v1, v2) / (norm(v1) * norm(v2)) = dot(v1, v2) / dim
        dot_product = np.dot(v1.astype(np.float32), v2.astype(np.float32))
        return float(dot_product / self.dim)
