import numpy as np


class BipolarVSA:
    def __init__(self, dim: int = 10000, seed: int = None):
        self.dim = dim
        # Instance-local RNG — avoids process-global np.random.seed side effects.
        self.rng = np.random.default_rng(seed)

    def generate_vector(self) -> np.ndarray:
        """Generates a random bipolar vector (+1 or -1) of dimension self.dim."""
        return self.rng.choice([-1, 1], size=self.dim).astype(np.int8)

    def bind(self, v1: np.ndarray, v2: np.ndarray) -> np.ndarray:
        """Binds two bipolar vectors using element-wise multiplication.

        Binding is reversible: bind(bind(a, b), b) approximates a.
        """
        return (v1 * v2).astype(np.int8)

    def permute(self, v: np.ndarray, shifts: int = 1) -> np.ndarray:
        """Permutes a bipolar vector using cyclic shift (np.roll)."""
        return np.roll(v, shifts)

    def bundle(
        self,
        vectors: list[np.ndarray],
        weights: list[int] | None = None,
    ) -> np.ndarray:
        """Bundles multiple bipolar vectors using (optionally weighted) majority vote.

        If the sum is 0 (tie), a random +1 or -1 is chosen via the instance RNG.
        When ``weights`` is None, each vector contributes equally (legacy behaviour).
        """
        if not vectors:
            raise ValueError("Cannot bundle an empty list of vectors.")
        if len(vectors) == 1 and (weights is None or weights == [1]):
            return vectors[0].copy()

        if weights is None:
            weights = [1] * len(vectors)
        if len(weights) != len(vectors):
            raise ValueError(
                f"weights length ({len(weights)}) must match vectors length ({len(vectors)})."
            )

        stacked = np.stack(vectors, axis=0).astype(np.int32)
        weight_arr = np.asarray(weights, dtype=np.int32).reshape(-1, 1)
        summed = np.sum(stacked * weight_arr, axis=0)

        # Majority vote
        bundled = np.sign(summed).astype(np.int8)

        # Handle ties (where sign is 0) by randomly assigning +1 or -1
        ties = bundled == 0
        if np.any(ties):
            random_choices = self.rng.choice([-1, 1], size=int(np.sum(ties))).astype(np.int8)
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
