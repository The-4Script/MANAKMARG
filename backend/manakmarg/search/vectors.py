"""Corpus-trained LSA vectors (spec §8): TF-IDF over words and character n-grams, reduced with TruncatedSVD.

Vectors only order candidates; they never decide status. Small corpora skip the SVD and use the normalised
TF-IDF space directly. A neural sentence-embedding model can implement the same ``VectorIndex`` interface later
(its model download is deferred).
"""

from pathlib import Path

import joblib
import numpy as np
from scipy.sparse import hstack
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from sqlalchemy.engine import Connection

MIN_DOCS_FOR_SVD = 200
# The API only queries the listing index (hybrid product matching); the others are built for analysis and tests.
RUNTIME_CORPORA = ("coverage",)

CORPORA = {
    "coverage": """
        SELECT coverage_id, product_name || ' ' || COALESCE(category, '') || ' ' || COALESCE(product_category, '')
               || ' ' || COALESCE(standard_title_raw, '')
          FROM scheme_coverage WHERE is_current = 1""",
    "standards": "SELECT standard_id, COALESCE(title_clean, title) FROM standard WHERE is_current = 1",
    "faq": "SELECT faq_id, question || ' ' || answer FROM faq WHERE is_current = 1",
}


class VectorIndex:
    def __init__(self, ids: list[str], word: TfidfVectorizer, char: TfidfVectorizer, svd: TruncatedSVD | None, matrix):
        self.ids = ids
        self.word = word
        self.char = char
        self.svd = svd
        self.matrix = matrix

    @classmethod
    def build(cls, ids: list, texts: list[str], *, dimensions: int = 256, random_state: int = 7) -> "VectorIndex":
        if not ids:
            raise ValueError("cannot build a vector index from an empty corpus")
        word = TfidfVectorizer(lowercase=True, token_pattern=r"(?u)\b\w+\b", ngram_range=(1, 2), sublinear_tf=True)
        char = TfidfVectorizer(lowercase=True, analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        features = hstack([word.fit_transform(texts), char.fit_transform(texts)]).tocsr()
        svd = None
        if len(ids) >= MIN_DOCS_FOR_SVD:
            components = min(dimensions, features.shape[1] - 1, len(ids) - 1)
            svd = TruncatedSVD(n_components=components, random_state=random_state)
            matrix = normalize(svd.fit_transform(features))
        else:
            matrix = normalize(features)
        return cls([str(item) for item in ids], word, char, svd, matrix)

    def _embed(self, text: str):
        features = hstack([self.word.transform([text]), self.char.transform([text])]).tocsr()
        return normalize(self.svd.transform(features)) if self.svd is not None else normalize(features)

    def query(self, text: str, k: int = 10) -> list[tuple[str, float]]:
        if not text or not text.strip():
            return []
        similarities = self.matrix @ self._embed(text).T
        scores = np.asarray(similarities.todense() if hasattr(similarities, "todense") else similarities).ravel()
        top = np.argsort(-scores)[:k]
        return [(self.ids[index], float(scores[index])) for index in top if scores[index] > 0]

    def save(self, directory: Path, name: str) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.joblib"
        joblib.dump({"ids": self.ids, "word": self.word, "char": self.char, "svd": self.svd, "matrix": self.matrix}, path)
        return path

    @classmethod
    def load(cls, directory: Path, name: str) -> "VectorIndex":
        data = joblib.load(Path(directory) / f"{name}.joblib")
        return cls(data["ids"], data["word"], data["char"], data["svd"], data["matrix"])


def build_vector_indexes(
    conn: Connection, directory: Path, *, dimensions: int = 256, corpora: tuple[str, ...] | None = None
) -> dict[str, int]:
    """Build and save one index per corpus; returns document counts (empty corpora are skipped)."""
    counts = {}
    for name, sql in CORPORA.items():
        if corpora is not None and name not in corpora:
            continue
        rows = conn.exec_driver_sql(sql).all()
        if not rows:
            counts[name] = 0
            continue
        VectorIndex.build([row[0] for row in rows], [row[1] or "" for row in rows], dimensions=dimensions).save(directory, name)
        counts[name] = len(rows)
    return counts


def load_vector_indexes(directory: Path, names: tuple[str, ...] | None = None) -> dict[str, VectorIndex]:
    directory = Path(directory)
    wanted = names if names is not None else tuple(CORPORA)
    return {name: VectorIndex.load(directory, name) for name in wanted if (directory / f"{name}.joblib").exists()}
