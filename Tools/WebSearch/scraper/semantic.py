"""Semantic store for WebSearcherMCP: FastEmbed (int8 MiniLM) + Postgres/pgvector + polars.

Everything heavy (fastembed, psycopg) is imported lazily so the MCP server starts fast.
Environment:
    WEBSCRAPER_EMBED_MODEL   embedding model key (default: multilingual MiniLM-L12, int8 ONNX)
    WEBSCRAPER_PG_DSN        full libpq DSN; or build it from the variables below
    WEBSCRAPER_PG_HOST/PORT/USER/DB/PASSWORD   defaults 127.0.0.1 / 5433 / webscraper / webscraper
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache
from typing import Any

import polars as pl

#: Built-in FastEmbed model shipped as int8 ONNX ("-Q"); 384 dims; handles Portuguese and English.
MULTILINGUAL_INT8 = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
#: English-only int8 alternative, registered as a custom FastEmbed model on first use.
ENGLISH_INT8 = "all-MiniLM-L6-v2-int8"
DEFAULT_MODEL = MULTILINGUAL_INT8
DIM = 384


class SemanticError(RuntimeError):
    """Raised for configuration or storage problems the caller can act on."""


@lru_cache(maxsize=2)
def get_embedder(model: str | None = None) -> Any:
    """Return a cached single-thread FastEmbed ``TextEmbedding`` for ``model``."""
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    name = model or os.environ.get("WEBSCRAPER_EMBED_MODEL") or DEFAULT_MODEL
    if name == ENGLISH_INT8:
        try:
            TextEmbedding.add_custom_model(
                model=ENGLISH_INT8,
                pooling=PoolingType.MEAN,
                normalization=True,
                sources=ModelSource(hf="Xenova/all-MiniLM-L6-v2"),
                dim=DIM,
                model_file="onnx/model_quantized.onnx",
            )
        except ValueError:  # already registered in this process
            pass
    return TextEmbedding(name, threads=1)


def warmup(models: list[str | None]) -> list[tuple[str, float, float]]:
    """Load each model (downloading it if needed) and embed once.

    Returns ``(model, load_seconds, embed_ms)`` rows. The tokenizer used for chunking is cached too.
    """
    import time

    rows: list[tuple[str, float, float]] = []
    for model in models:
        name = model or os.environ.get("WEBSCRAPER_EMBED_MODEL") or DEFAULT_MODEL
        t0 = time.perf_counter()
        get_embedder(model)
        counting_tokenizer(model)
        load = time.perf_counter() - t0
        t1 = time.perf_counter()
        embed_texts(["warm up"], model)
        rows.append((name, load, (time.perf_counter() - t1) * 1000))
    return rows


def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Embed ``texts`` into L2-normalised float vectors of ``DIM`` dimensions."""
    vectors = [list(map(float, v)) for v in get_embedder(model).embed(texts)]
    for v in vectors:
        if len(v) != DIM:
            raise SemanticError(f"model returned {len(v)} dims, store expects {DIM}")
    return vectors


@lru_cache(maxsize=2)
def counting_tokenizer(model: str | None = None) -> tuple[Any, int]:
    """Return ``(tokenizer, limit)`` for ``model``: an untruncated copy and its usable token limit.

    The embedder's own tokenizer truncates to the model's training length (128 tokens for the
    multilingual MiniLM) and drops the rest silently. Chunks must fit that length, so the limit is
    read from the embedder and the copy counts tokens without truncating or padding.
    """
    from tokenizers import Tokenizer

    own = get_embedder(model).model.tokenizer
    trunc = own.truncation
    limit = (trunc["max_length"] if trunc else 512) - 2  # room for [CLS]/[SEP]
    copy = Tokenizer.from_str(own.to_str())
    copy.no_truncation()
    copy.no_padding()
    return copy, limit


_SENTENCE = re.compile(r"(?<=[.!?\u3002])\s+")


def _units(text: str) -> list[tuple[str, bool]]:
    """Split ``text`` into sentence-sized units; the flag marks the first unit of a paragraph."""
    units: list[tuple[str, bool]] = []
    for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        for i, sent in enumerate(x for x in _SENTENCE.split(para) if x.strip()):
            units.append((sent.strip(), i == 0))
    return units


def _hard_split(unit: str, tok: Any, limit: int, overlap: int) -> list[str]:
    """Cut one over-long unit into token windows that each re-tokenize to ``limit`` or fewer.

    Windows are cut at the tokenizer's character offsets. A slice can start mid-word and then
    tokenize one token longer on its own, so each piece is re-counted and shortened until it fits.
    """
    enc = tok.encode(unit, add_special_tokens=False)
    total = len(enc.ids)
    out: list[str] = []
    start = 0
    while start < total:
        end = min(start + limit, total)
        while True:
            piece = unit[enc.offsets[start][0] : enc.offsets[end - 1][1]]
            if end - start <= 1 or len(tok.encode(piece, add_special_tokens=False).ids) <= limit:
                break
            end -= 1
        out.append(piece)
        if end >= total:
            break
        start = max(start + 1, end - overlap)
    return out


def chunk_with_tokenizer(
    url: str, text: str, tok: Any, limit: int, overlap_ratio: float = 0.12, min_tokens: int = 8
) -> pl.DataFrame:
    """Pack sentences into chunks of at most ``limit`` tokens, with a token-based overlap.

    Columns: ``url``, ``chunk_idx``, ``text``, ``sha`` (content hash, used for dedupe),
    ``n_tokens``.
    """
    overlap = int(limit * overlap_ratio)
    pieces: list[tuple[str, bool]] = []
    for unit, starts_para in _units(text):
        if len(tok.encode(unit, add_special_tokens=False).ids) > limit:
            pieces += [
                (w, starts_para and i == 0)
                for i, w in enumerate(_hard_split(unit, tok, limit, overlap))
            ]
        else:
            pieces.append((unit, starts_para))
    counts = [
        len(e.ids) for e in tok.encode_batch([u for u, _ in pieces], add_special_tokens=False)
    ]

    chunks: list[str] = []
    cur: list[int] = []  # indices into pieces

    def render(idx: list[int]) -> str:
        out = ""
        for k, i in enumerate(idx):
            sep = "" if k == 0 else ("\n\n" if pieces[i][1] else " ")
            out += sep + pieces[i][0]
        return out

    total = 0
    for i, n in enumerate(counts):
        if cur and total + n > limit:
            chunks.append(render(cur))
            keep: list[int] = []
            kept = 0
            for j in reversed(cur):  # carry the tail forward as overlap
                if kept + counts[j] > overlap:
                    break
                keep.insert(0, j)
                kept += counts[j]
            while keep and kept + n > limit:  # the carried tail must leave room for this unit
                kept -= counts[keep.pop(0)]
            cur, total = keep, kept
        cur.append(i)
        total += n
    if cur:
        chunks.append(render(cur))

    fitted: list[str] = []
    for chunk, enc in zip(chunks, tok.encode_batch(chunks, add_special_tokens=False), strict=True):
        # the joined text can tokenize longer than the sum of its sentences: re-split if so
        fitted += [chunk] if len(enc.ids) <= limit else _hard_split(chunk, tok, limit, overlap)
    chunks = fitted

    frame = pl.DataFrame({"text": chunks}, schema={"text": pl.String})
    frame = frame.with_columns(
        pl.Series(
            "n_tokens", [len(e.ids) for e in tok.encode_batch(chunks, add_special_tokens=False)]
        )
        if chunks
        else pl.lit(0).alias("n_tokens")
    )
    return (
        frame.filter(pl.col("n_tokens") >= min_tokens)
        .with_columns(
            pl.lit(url).alias("url"),
            pl.col("text")
            .map_elements(
                lambda t: hashlib.sha256(t.encode()).hexdigest()[:16], return_dtype=pl.String
            )
            .alias("sha"),
        )
        .unique(subset=["sha"], keep="first", maintain_order=True)
        .with_row_index("chunk_idx")
        .select("url", "chunk_idx", "text", "sha", "n_tokens")
    )


def chunk_by_tokens(url: str, text: str, model: str | None = None) -> pl.DataFrame:
    """Chunk ``text`` so every chunk fits the embedding model's token window."""
    tok, limit = counting_tokenizer(model)
    return chunk_with_tokenizer(url, text, tok, limit)


_STOP = frozenset(
    (
        "a an and are as at be by for from how in is it of on or that the to was what with "
        "o os as de da do das dos em um uma uns umas para com sem por nao não e ou se que "
        "ao aos na nas no nos"
    ).split()
)


def query_terms(query: str) -> set[str]:
    """Distinct query tokens used for keyword rerank (PT/EN stopwords dropped)."""
    return {t for t in re.findall(r"\w{2,}", query.lower()) if t not in _STOP}


def rerank(
    hits: pl.DataFrame,
    query: str,
    weight: float = 0.15,
    min_similarity: float = 0.0,
) -> pl.DataFrame:
    """Blend vector similarity with unique query-term coverage and sort by the result."""
    frame = hits
    if min_similarity > 0 and "similarity" in frame.columns and not frame.is_empty():
        frame = frame.filter(pl.col("similarity") >= min_similarity)
    terms = query_terms(query)
    if frame.is_empty() or not terms:
        if "score" in frame.columns:
            return frame.sort("score", descending=True)
        if "similarity" in frame.columns:
            return frame.sort("similarity", descending=True)
        return frame
    def _coverage(text: str) -> float:
        found = set(re.findall(r"\w{2,}", text.lower()))
        return len(terms & found) / len(terms)

    return (
        frame.with_columns(
            pl.col("text").map_elements(_coverage, return_dtype=pl.Float64).alias("kw")
        )
        .with_columns((pl.col("similarity") * (1 - weight) + pl.col("kw") * weight).alias("score"))
        .sort("score", descending=True)
    )


def dsn_kwargs() -> dict[str, Any]:
    """Connection arguments from the environment (password never logged)."""
    if dsn := os.environ.get("WEBSCRAPER_PG_DSN"):
        return {"conninfo": dsn}
    password = os.environ.get("WEBSCRAPER_PG_PASSWORD")
    if not password:
        raise SemanticError("set WEBSCRAPER_PG_PASSWORD (or WEBSCRAPER_PG_DSN)")
    env = os.environ.get
    return {
        "host": env("WEBSCRAPER_PG_HOST", "127.0.0.1"),
        "port": int(env("WEBSCRAPER_PG_PORT", "5433")),
        "user": env("WEBSCRAPER_PG_USER", "webscraper"),
        "dbname": env("WEBSCRAPER_PG_DB", "webscraper"),
        "password": password,
    }


class PgVectorStore:
    """Chunk store on Postgres + pgvector with an HNSW cosine index."""

    def __init__(self, table: str = "web_chunks") -> None:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", table):
            raise SemanticError(f"invalid table name {table!r}")
        self.table = table
        self._conn: Any = None

    def connect(self) -> Any:
        """Open the connection and create the extension, table and index on first use."""
        if self._conn is not None and not self._conn.closed:
            return self._conn
        import psycopg
        from pgvector.psycopg import register_vector

        try:
            conn = psycopg.connect(**dsn_kwargs(), autocommit=True, connect_timeout=5)
        except psycopg.OperationalError as exc:
            raise SemanticError(f"cannot reach Postgres: {exc}") from exc
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)
        conn.execute(
            f"""CREATE TABLE IF NOT EXISTS {self.table} (
                url text NOT NULL, chunk_idx int NOT NULL, text text NOT NULL, sha text NOT NULL,
                model text NOT NULL, embedding vector({DIM}) NOT NULL, n_tokens int,
                fetched_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (url, chunk_idx))"""
        )
        conn.execute(f"ALTER TABLE {self.table} ADD COLUMN IF NOT EXISTS n_tokens int")
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.table}_hnsw ON {self.table} "
            "USING hnsw (embedding vector_cosine_ops)"
        )
        self._conn = conn
        return conn

    def replace_url(
        self, url: str, chunks: pl.DataFrame, vectors: list[list[float]], model: str
    ) -> int:
        """Atomically replace every stored chunk of ``url``; returns the chunk count."""
        conn = self.connect()
        if "n_tokens" not in chunks.columns:  # callers without token counts store NULL
            chunks = chunks.with_columns(pl.lit(None, dtype=pl.Int64).alias("n_tokens"))
        rows = [
            (url, int(i), t, s, model, v, n)
            for (i, t, s, n), v in zip(
                chunks.select("chunk_idx", "text", "sha", "n_tokens").iter_rows(),
                vectors,
                strict=True,
            )
        ]
        with conn.transaction():
            conn.execute(f"DELETE FROM {self.table} WHERE url = %s", (url,))
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {self.table} "
                    "(url, chunk_idx, text, sha, model, embedding, n_tokens) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    rows,
                )
        return len(rows)

    def search(
        self, vector: list[float], model: str, limit: int = 5, url_contains: str | None = None
    ) -> pl.DataFrame:
        """Nearest chunks by cosine distance (same ``model`` only) as a polars frame."""
        conn = self.connect()
        where, params = "model = %s", [model]
        if url_contains:
            where += " AND url ILIKE %s"
            params.append(f"%{url_contains}%")
        cur = conn.execute(
            f"SELECT url, chunk_idx, text, COALESCE(n_tokens, 0) AS n_tokens, "
            f"1 - (embedding <=> %s::vector) AS similarity "
            f"FROM {self.table} WHERE {where} ORDER BY embedding <=> %s::vector LIMIT %s",
            [vector, *params, vector, limit * 4],
        )
        rows = cur.fetchall()
        return pl.DataFrame(
            rows,
            schema={
                "url": pl.String,
                "chunk_idx": pl.Int64,
                "text": pl.String,
                "n_tokens": pl.Int64,
                "similarity": pl.Float64,
            },
            orient="row",
        )

    def stats(self) -> pl.DataFrame:
        """Chunks and distinct models per URL."""
        cur = self.connect().execute(
            f"SELECT url, count(*) AS chunks, max(fetched_at)::text AS fetched_at "
            f"FROM {self.table} GROUP BY url ORDER BY max(fetched_at) DESC"
        )
        return pl.DataFrame(
            cur.fetchall(),
            schema={"url": pl.String, "chunks": pl.Int64, "fetched_at": pl.String},
            orient="row",
        )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
