"""Vector embedding utilities, local neural hashing, and cloud embedding providers for Rusty."""

from __future__ import annotations

import hashlib
import math
import re
from typing import List, Optional

import numpy as np

EMBEDDING_DIM = 384


def vector_to_blob(vec: list[float] | np.ndarray) -> bytes:
    """Serialize a float vector to binary BLOB for SQLite storage."""
    arr = np.asarray(vec, dtype=np.float32)
    return arr.tobytes()


def blob_to_vector(blob: bytes) -> np.ndarray:
    """Deserialize binary BLOB from SQLite to a numpy float32 array."""
    if not blob:
        return np.zeros(EMBEDDING_DIM, dtype=np.float32)
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Calculate cosine similarity between two 1D vectors."""
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


def batch_cosine_similarity(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Calculate cosine similarity between a single query vector and a 2D matrix of vectors."""
    if matrix.size == 0:
        return np.array([], dtype=np.float32)
    q_norm = np.linalg.norm(query_vec)
    if q_norm == 0.0:
        return np.zeros(len(matrix), dtype=np.float32)
    m_norms = np.linalg.norm(matrix, axis=1)
    m_norms[m_norms == 0.0] = 1.0
    dots = np.dot(matrix, query_vec)
    return dots / (m_norms * q_norm)


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words and n-grams."""
    cleaned = re.sub(r"[^\w\s]", " ", (text or "").lower())
    words = [w for w in cleaned.split() if len(w) > 1]
    tokens = list(words)
    # Add word bigrams for phrase awareness
    for i in range(len(words) - 1):
        tokens.append(f"{words[i]}_{words[i+1]}")
    # Add character trigrams for typo-tolerance and subword semantics
    for w in words:
        if len(w) >= 3:
            for j in range(len(w) - 2):
                tokens.append(f"#{w[j:j+3]}")
    return tokens


def local_deterministic_embedding(text: str, dim: int = EMBEDDING_DIM) -> np.ndarray:
    """Fast, zero-dependency, local semantic hashing vectorizer.
    Produces a 384-dimensional L2-normalized vector capturing lexical, phrase, and subword semantics."""
    tokens = _tokenize(text)
    if not tokens:
        return np.zeros(dim, dtype=np.float32)

    vec = np.zeros(dim, dtype=np.float32)
    for tok in tokens:
        # Generate 2 distinct hash buckets per token to reduce collisions
        h1 = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
        h2 = int(hashlib.sha1(tok.encode("utf-8")).hexdigest()[:8], 16)
        idx1 = h1 % dim
        idx2 = h2 % dim
        sign1 = 1.0 if (h1 & 0x100) else -1.0
        sign2 = 1.0 if (h2 & 0x100) else -1.0
        
        # Sub-linear term frequency weighting
        vec[idx1] += sign1
        vec[idx2] += sign2 * 0.5

    # L2 normalize
    norm = np.linalg.norm(vec)
    if norm > 0.0:
        vec = vec / norm
    return vec.astype(np.float32)


def get_embedding(text: str, config: dict = None) -> np.ndarray:
    """Generate embedding vector for text using configured cloud provider with local fallback."""
    if not text or not text.strip():
        return np.zeros(EMBEDDING_DIM, dtype=np.float32)

    # Check if cloud embedding is enabled and key exists
    llm_cfg = (config or {}).get("llm", {})
    api_key = llm_cfg.get("api_key")
    provider = llm_cfg.get("provider", "google")

    if api_key and provider == "google":
        try:
            from openai import OpenAI
            base_url = llm_cfg.get("base_url") or "https://generativelanguage.googleapis.com/v1beta/openai/"
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=5.0)
            res = client.embeddings.create(
                model="text-embedding-004",
                input=text[:2000]
            )
            emb = res.data[0].embedding
            arr = np.asarray(emb, dtype=np.float32)
            # Truncate or pad to EMBEDDING_DIM if necessary
            if len(arr) >= EMBEDDING_DIM:
                arr = arr[:EMBEDDING_DIM]
            else:
                arr = np.pad(arr, (0, EMBEDDING_DIM - len(arr)))
            norm = np.linalg.norm(arr)
            return (arr / norm if norm > 0 else arr).astype(np.float32)
        except Exception:
            pass  # Seamless fallback to local deterministic vector

    return local_deterministic_embedding(text, dim=EMBEDDING_DIM)
