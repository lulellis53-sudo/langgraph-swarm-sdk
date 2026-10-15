"""Tests for the semantic store, the LLM fallback chain and the sourced-answer tool."""

from __future__ import annotations

import asyncio
import os

import httpx2
import polars as pl
import pytest
from WebSearch.scraper import llm, semantic
from WebSearch.scraper import websearcher_mcp as mod


@pytest.fixture(autouse=True)
def _real_agent_clis_look_uninstalled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never launch the real Claude Code / Codex CLIs (logged in on this machine)."""
    real_which = llm.shutil.which

    def which(cmd: str, *a, **kw):
        return None if cmd in {"claude", "codex"} else real_which(cmd, *a, **kw)

    monkeypatch.setattr(llm.shutil, "which", which)


def _word_tokenizer(words: list[str]):
    from tokenizers import Tokenizer, models, pre_tokenizers

    tok = Tokenizer(models.WordLevel({w: i for i, w in enumerate(["[UNK]", *words])}, "[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    return tok


WORDS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa"]


def test_chunks_never_exceed_token_limit_and_overlap() -> None:
    tok = _word_tokenizer(WORDS)
    sentence = "alpha beta gamma delta epsilon."  # 6 tokens: five words and the full stop
    text = "\n\n".join(" ".join([sentence] * 4) for _ in range(5))
    frame = semantic.chunk_with_tokenizer("http://x", text, tok, limit=20, overlap_ratio=0.3)
    assert frame.columns == ["url", "chunk_idx", "text", "sha", "n_tokens"]
    assert frame["n_tokens"].max() <= 20
    assert frame.height > 1
    assert frame["chunk_idx"].to_list() == list(range(frame.height))
    first, second = frame["text"].to_list()[:2]
    assert first.split()[-1] in second  # overlap carries the tail into the next chunk


def test_overlap_tail_plus_next_sentence_still_fits_the_limit() -> None:
    tok = _word_tokenizer(WORDS)
    short = "alpha beta gamma delta."  # 5 tokens, small enough to be carried as overlap
    long = " ".join(["epsilon"] * 17) + "."  # 18 tokens: 5 + 18 > 20 once the tail is carried
    frame = semantic.chunk_with_tokenizer(
        "http://x", f"{short} {long} {short} {long}", tok, limit=20, overlap_ratio=0.3, min_tokens=1
    )
    assert frame.height >= 2
    assert frame["n_tokens"].max() <= 20


def test_oversized_sentence_is_hard_split_by_tokens() -> None:
    tok = _word_tokenizer(WORDS)
    text = " ".join(WORDS * 6)  # one 60-token "sentence" without punctuation
    frame = semantic.chunk_with_tokenizer("http://x", text, tok, limit=16, overlap_ratio=0.25)
    assert frame["n_tokens"].max() <= 16
    assert "".join(frame["text"].to_list()).count("alpha") >= 6  # nothing lost


def test_chunking_dedupes_and_drops_tiny_chunks() -> None:
    tok = _word_tokenizer(WORDS)
    para = "alpha beta gamma delta epsilon zeta eta theta iota kappa alpha beta."
    frame = semantic.chunk_with_tokenizer("http://x", f"{para}\n\nhi\n\n{para}", tok, limit=40)
    assert frame["sha"].n_unique() == frame.height
    assert "hi" not in frame["text"].to_list()


def test_chunking_empty_text() -> None:
    tok = _word_tokenizer(WORDS)
    assert semantic.chunk_with_tokenizer("http://x", "   ", tok, limit=20).is_empty()


def _real_tokenizer():
    try:
        return semantic.counting_tokenizer(None)
    except Exception:
        return None


@pytest.mark.skipif(_real_tokenizer() is None, reason="embedding model not available offline")
def test_real_model_chunks_fit_the_embedding_window() -> None:
    tok, limit = _real_tokenizer()
    assert limit == 126  # 128-token window minus [CLS] and [SEP]
    text = "\n\n".join(
        "Task groups combine a task creation API with a convenient way to wait for all tasks. "
        "Uma segunda frase em português para misturar idiomas no mesmo parágrafo de teste. " * 3
        for _ in range(8)
    )
    frame = semantic.chunk_by_tokens("http://x", text)
    assert frame.height > 3
    assert frame["n_tokens"].max() <= limit
    # the embedder sees every token: nothing is truncated away
    assert all(
        len(e.ids) <= limit
        for e in tok.encode_batch(frame["text"].to_list(), add_special_tokens=False)
    )


def test_rerank_boosts_keyword_matches() -> None:
    hits = pl.DataFrame(
        {
            "url": ["a", "b"],
            "chunk_idx": [0, 0],
            "text": ["nothing relevant here at all", "taskgroup taskgroup explained"],
            "similarity": [0.60, 0.58],
        }
    )
    out = semantic.rerank(hits, "taskgroup", weight=0.3)
    assert out["url"].to_list() == ["b", "a"]


def test_rerank_min_similarity_drops_weak_vectors() -> None:
    hits = pl.DataFrame(
        {
            "url": ["a", "b"],
            "chunk_idx": [0, 0],
            "text": ["taskgroup notes", "unrelated"],
            "similarity": [0.80, 0.10],
        }
    )
    out = semantic.rerank(hits, "taskgroup", min_similarity=0.3)
    assert out["url"].to_list() == ["a"]


def test_dsn_requires_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBSCRAPER_PG_DSN", raising=False)
    monkeypatch.delenv("WEBSCRAPER_PG_PASSWORD", raising=False)
    with pytest.raises(semantic.SemanticError):
        semantic.dsn_kwargs()
    monkeypatch.setenv("WEBSCRAPER_PG_PASSWORD", "pw")
    assert semantic.dsn_kwargs()["port"] == 5433


def test_store_rejects_bad_table_name() -> None:
    with pytest.raises(semantic.SemanticError):
        semantic.PgVectorStore("x; drop table y")


def _pg_up() -> bool:
    if not os.environ.get("WEBSCRAPER_PG_PASSWORD") and not os.environ.get("WEBSCRAPER_PG_DSN"):
        return False
    try:
        semantic.PgVectorStore("t_probe").connect().close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pg_up(), reason="Postgres/pgvector not reachable or no password in env")
def test_pgvector_roundtrip() -> None:
    store = semantic.PgVectorStore("t_semantic_roundtrip")
    conn = store.connect()
    try:
        conn.execute("TRUNCATE t_semantic_roundtrip")
        near = [1.0] + [0.0] * (semantic.DIM - 1)
        far = [0.0, 1.0] + [0.0] * (semantic.DIM - 2)
        frame = pl.DataFrame(
            {"chunk_idx": [0, 1], "text": ["near chunk", "far chunk"], "sha": ["s0", "s1"]}
        )
        assert store.replace_url("http://u", frame, [near, far], "m") == 2
        assert store.replace_url("http://u", frame, [near, far], "m") == 2  # replace, not append
        hits = store.search(near, "m", limit=1)
        assert hits["text"].to_list()[0] == "near chunk"
        assert store.search(near, "other-model").is_empty()
        assert store.stats()["chunks"].to_list() == [2]
    finally:
        conn.execute("DROP TABLE IF EXISTS t_semantic_roundtrip")
        store.close()


def test_llm_chain_skips_rejected_providers(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    f = _yaml(
        tmp_path,
        """
providers:
  - {name: groq, base_url: "https://api.groq.com/v1", keys: [T_GROQ], model: m, maxretry: 0}
  - {name: novita, base_url: "https://api.novita.ai/v1", keys: [T_NOVITA], model: m, maxretry: 0}
  - {name: atlas, base_url: "https://atlas.example/v1", keys: [T_ATLAS], model: m, maxretry: 0}
  - {name: openrouter, base_url: "https://openrouter.ai/v1", keys: [T_OR], model: m, maxretry: 0}
""",
    )
    for name in ("T_GROQ", "T_NOVITA", "T_OR"):
        monkeypatch.setenv(name, "k")
    monkeypatch.delenv("T_ATLAS", raising=False)
    monkeypatch.delenv("LLM_FIRST", raising=False)
    seen: list[str] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req.url.host)
        if "groq" in req.url.host:
            return httpx2.Response(401)
        if "novita" in req.url.host:
            return httpx2.Response(403)
        return httpx2.Response(200, json={"choices": [{"message": {"content": " Paris "}}]})

    async def run() -> tuple[str, str]:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            return await llm.chat("capital?", providers=llm.load_providers(f), client=client)

    text, used = asyncio.run(run())
    assert text == "Paris"
    assert used.startswith("openrouter/")
    assert seen == ["api.groq.com", "api.novita.ai", "openrouter.ai"]  # atlas had no key


def test_llm_chain_raises_when_nobody_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    for p in llm.PROVIDERS:
        for env in p.key_envs:
            monkeypatch.delenv(env, raising=False)
    with pytest.raises(llm.LLMError):
        asyncio.run(llm.chat("x"))


def test_ask_with_sources_lists_real_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def hits(q: str, limit: int, url_contains: str | None = None):
        return [
            {
                "title": "http://store#0",
                "url": "http://store",
                "snippet": "stored text\n\nwith a blank line",
                "score": 0.9,
                "chunk_idx": 0,
            }
        ]

    async def searx(q: str, limit: int):
        return [{"title": "t", "url": "http://web", "content": "web text"}]

    async def fake_chat(prompt: str, system: str | None = None, **kw):
        assert "[1] http://store" in prompt and "[2] http://web" in prompt
        return "answer [1]", "fake/model"

    monkeypatch.setattr(mod, "_semantic_rows", hits)
    monkeypatch.setattr(mod, "_searx_results", searx)
    monkeypatch.setattr(mod.llm, "_loaded_module", type("L", (), {"chat": staticmethod(fake_chat)}))
    out = asyncio.run(mod.ask_with_sources("q"))
    assert out.startswith("answer [1]")
    assert "[1] http://store" in out and "[2] http://web" in out
    assert "(model: fake/model)" in out


def test_llm_chain_tries_every_key_of_a_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    for p in llm.PROVIDERS:
        for env in p.key_envs:
            monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "bad")
    monkeypatch.setenv("GROQ_API_KEY_1", "good")
    used: list[str] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        used.append(req.headers["authorization"])
        if req.headers["authorization"] == "Bearer bad":
            return httpx2.Response(401)
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async def run() -> tuple[str, str]:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            return await llm.chat("x", client=client)

    assert asyncio.run(run())[1].startswith("groq/")
    assert used == ["Bearer bad", "Bearer good"]


def test_llm_first_moves_provider_to_the_front(monkeypatch: pytest.MonkeyPatch) -> None:
    for p in llm.PROVIDERS:
        for env in p.key_envs:
            monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("TOKEN_HARBOR_API_KEY", "t")
    monkeypatch.setenv("LLM_FIRST", "tokenharbor")
    monkeypatch.setenv("TOKENHARBOR_MODEL", "claude-sonnet-5.5")
    calls: list[tuple[str, str]] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        import json

        calls.append((req.url.host, json.loads(req.content)["model"]))
        return httpx2.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    async def run() -> tuple[str, str]:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            return await llm.chat("x", client=client)

    assert asyncio.run(run())[1] == "tokenharbor/claude-sonnet-5.5"
    assert calls == [("tokenharbor.ai", "claude-sonnet-5.5")]


def test_probe_reports_status_per_key_without_leaking_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for p in llm.PROVIDERS:
        for env in p.key_envs:
            monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "secret-a")
    monkeypatch.setenv("GROQ_API_KEY_1", "secret-b")

    def handler(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401 if req.headers["authorization"].endswith("a") else 200, json={})

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            return await llm.probe(client=client)

    rows = {label: status for label, status, _ in asyncio.run(run())}
    assert rows["groq#1"] == "401" and rows["groq#2"] == "200"
    assert rows["tokenharbor"] == "no key"
    assert "secret" not in repr(rows)


def test_health_check_reports_every_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    async def status(url: str, headers=None) -> str:
        return "200" if "healthz" in url or "/health" in url else "503"

    class FakeStore:
        def stats(self):
            return pl.DataFrame({"url": ["u"], "chunks": [3], "fetched_at": ["t"]})

    monkeypatch.setattr(mod, "_get_status", status)
    monkeypatch.setattr(mod, "_store", lambda: FakeStore())
    monkeypatch.setenv("CRAWL4AI_API_TOKEN", "tok-secret")
    out = asyncio.run(mod.health_check())
    assert "searxng      ok" in out and "crawl4ai     ok" in out and "token set" in out
    assert "pgvector     ok 3 chunks, 1 URLs" in out
    assert "perplexica   FAIL (HTTP 503)" in out
    assert "tok-secret" not in out


@pytest.mark.skipif(_real_tokenizer() is None, reason="embedding model not available offline")
def test_real_model_markup_heavy_text_fits_the_window() -> None:
    tok, limit = _real_tokenizer()
    link = (
        "_class_ asyncio.TaskGroup[¶](https://docs.python.org/3/library/asyncio-task.html"
        '#asyncio.TaskGroup "Link to this definition")'
    )
    text = "\n\n".join(
        f"{link} An [asynchronous context manager](https://docs.python.org/3/reference/"
        f"datamodel.html#async-context-managers) holding a group of tasks (see {i}). "
        f"Tasks can be added with create_task()! Todas as tarefas são aguardadas, ok? {link}."
        for i in range(60)
    )
    frame = semantic.chunk_by_tokens("http://x", text)
    counts = [
        len(e.ids) for e in tok.encode_batch(frame["text"].to_list(), add_special_tokens=False)
    ]
    assert max(counts) <= limit
    assert counts == frame["n_tokens"].to_list()  # the stored count is the real count


class _MidWordTok:
    """Stub tokenizer: 3-character tokens, but a text that starts with "x" costs one extra token.

    Mimics a real subword tokenizer, where a slice cut mid-word re-tokenizes one token longer.
    """

    def encode(self, text: str, add_special_tokens: bool = False):
        from types import SimpleNamespace

        spans = [(i, min(i + 3, len(text))) for i in range(0, len(text), 3)]
        ids = list(range(len(spans))) + ([0] if text.startswith("x") else [])
        return SimpleNamespace(ids=ids, offsets=spans)

    def encode_batch(self, texts: list[str], add_special_tokens: bool = False):
        return [self.encode(t) for t in texts]


def test_hard_split_pieces_re_tokenize_within_the_limit() -> None:
    tok = _MidWordTok()
    unit = "abcxyzxyzxyzabcxyzabcabcxyzxyzabc" * 4
    pieces = semantic._hard_split(unit, tok, limit=6, overlap=1)
    assert len(pieces) > 1
    assert all(len(tok.encode(p).ids) <= 6 for p in pieces)  # the shrink loop made them fit


@pytest.mark.skipif(_real_tokenizer() is None, reason="embedding model not available offline")
def test_real_model_seeded_markup_never_exceeds_the_window() -> None:
    import random

    tok, limit = _real_tokenizer()
    rng = random.Random(7)
    slugs = [
        "coroutines",
        "awaitables",
        "creating-tasks",
        "task-cancellation",
        "timeouts",
        "taskgroup",
    ]
    lines = [
        f"    * [{rng.choice(slugs).replace('-', ' ').title()}]"
        f"(https://docs.python.org/3/library/asyncio-task.html#"
        f"{rng.choice(slugs)}{rng.randint(0, 99)})"
        for _ in range(900)
    ]
    frame = semantic.chunk_by_tokens("http://x", "\n".join(lines))
    counts = [
        len(e.ids) for e in tok.encode_batch(frame["text"].to_list(), add_special_tokens=False)
    ]
    assert max(counts) <= limit
    assert counts == frame["n_tokens"].to_list()


def test_warmup_loads_each_model_once_and_times_it(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[str | None] = []

    class FakeEmbedder:
        def embed(self, texts):
            return [[0.0] * semantic.DIM for _ in texts]

    monkeypatch.setattr(semantic, "get_embedder", lambda m=None: loaded.append(m) or FakeEmbedder())
    monkeypatch.setattr(semantic, "counting_tokenizer", lambda m=None: (None, 126))
    rows = semantic.warmup([None, semantic.ENGLISH_INT8])
    assert [r[0] for r in rows] == [semantic.DEFAULT_MODEL, semantic.ENGLISH_INT8]
    assert all(load >= 0 and ms >= 0 for _, load, ms in rows)
    assert loaded.count(None) >= 1 and semantic.ENGLISH_INT8 in loaded


def test_warmup_tool_reports_failures_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(models):
        raise OSError("no network")

    monkeypatch.setattr(
        mod.semantic,
        "_loaded_module",
        type("S", (), {"warmup": staticmethod(boom), "ENGLISH_INT8": "x"}),
    )
    assert "warmup failed: OSError" in asyncio.run(mod.warmup())


def _yaml(tmp_path, text: str):
    f = tmp_path / "p.yaml"
    f.write_text(text)
    return f


def test_providers_yaml_in_repo_is_valid_and_avoids_gemini() -> None:
    provs = llm.load_providers()
    by_name = {p.name: p for p in provs}
    names = [p.name for p in provs]
    assert len(names) == len(set(names))
    assert names.index("mistral") < names.index(
        "groq"
    )  # providers that answer come before dead ones
    free = {"mistral", "cohere", "nvidia", "ollama", "openrouter", "laguna", "tokenharbor"}
    assert free <= set(names)
    assert next(p for p in provs if p.name == "nvidia").extra_body["chat_template_kwargs"] == {
        "enable_thinking": False
    }
    assert not by_name["gemini"].enabled
    # off on purpose: Gemini (avoided), Step Flash routes (paid), Codex (can read files),
    # Z.ai (plan terms), and entries whose keys or balance are rejected today (mimo, sonnet)
    assert {n for n, p in by_name.items() if not p.enabled} == {
        "gemini",
        "stepflash",
        "stepfun",
        "codex",
        "zai",
        "mimo",
        "sonnet",
    }


def test_providers_yaml_defaults_and_effort_budget(tmp_path) -> None:
    f = _yaml(
        tmp_path,
        """
version: 1
defaults: {effort: high, maxretry: 2, maxms: 5000}
providers:
  - {name: a, base_url: "https://a.example/v1/", keys: [A_KEY], model: m1}
  - {name: b, base_url: "https://b.example/v1", keys: [B_KEY], model: m2, effort: low, maxms: 1000}
""",
    )
    a, b = llm.load_providers(f)
    assert (a.effort, a.maxretry, a.maxms, a.enabled, a.base_url) == (
        "high",
        2,
        5000,
        True,
        "https://a.example/v1",
    )
    assert (b.effort, b.maxretry, b.maxms) == ("low", 2, 1000)
    assert (a.max_tokens, b.max_tokens) == (1500, 300)


@pytest.mark.parametrize(
    "bad",
    [
        "providers: []\nnope: 1" if False else "version: 1",  # no providers list
        "providers:\n  - {name: a, base_url: x, keys: [K], model: m, effort: huge}",
        "providers:\n  - {name: a, base_url: x, keys: [K], model: m, maxretry: 9}",
        "providers:\n  - {name: a, base_url: x, keys: [K], model: m, maxms: 0}",
        "providers:\n  - {name: a, base_url: x, keys: [k], model: m}",
        "providers:\n  - {name: a, base_url: x, keys: [K], model: m, speed: 1}",
        "providers:\n  - {name: a, base_url: x, keys: [K], model: m}"
        "\n  - {name: a, base_url: y, keys: [K], model: m}",
    ],
)
def test_providers_yaml_rejects_invalid_entries(tmp_path, bad: str) -> None:
    with pytest.raises(llm.ConfigError):
        llm.load_providers(_yaml(tmp_path, bad))


def test_disabled_provider_is_never_called(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    f = _yaml(
        tmp_path,
        """
providers:
  - {name: dormant, base_url: "https://off.example/v1", keys: [OFF_KEY], model: m, enabled: false}
  - {name: active, base_url: "https://on.example/v1", keys: [ON_KEY], model: m}
""",
    )
    monkeypatch.setenv("OFF_KEY", "k")
    monkeypatch.setenv("ON_KEY", "k")
    monkeypatch.delenv("LLM_FIRST", raising=False)
    hosts: list[str] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        hosts.append(req.url.host)
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            return await llm.chat("x", providers=llm.load_providers(f), client=client)

    assert asyncio.run(run())[1] == "active/m"
    assert hosts == ["on.example"]


def test_effort_sets_max_tokens_and_maxms_sets_the_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    f = _yaml(
        tmp_path,
        """
providers:
  - {name: p, base_url: "https://p.example/v1", keys: [P_KEY], model: m, effort: xhigh, maxms: 2500}
""",
    )
    monkeypatch.setenv("P_KEY", "k")
    monkeypatch.delenv("LLM_FIRST", raising=False)
    seen: dict = {}

    def handler(req: httpx2.Request) -> httpx2.Response:
        import json

        seen["max_tokens"] = json.loads(req.content)["max_tokens"]
        seen["timeout"] = req.extensions["timeout"]["read"]
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async def run(**kw):
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            return await llm.chat("x", providers=llm.load_providers(f), client=client, **kw)

    asyncio.run(run())
    assert seen == {"max_tokens": 3000, "timeout": 2.5}
    asyncio.run(run(max_tokens=50))
    assert seen["max_tokens"] == 50  # an explicit budget wins over effort


def test_transient_failures_are_retried_up_to_maxretry(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(llm, "RETRY_BASE_S", 0)
    monkeypatch.setenv("R_KEY", "k")
    monkeypatch.delenv("LLM_FIRST", raising=False)
    f = _yaml(
        tmp_path,
        """
providers:
  - {name: r, base_url: "https://r.example/v1", keys: [R_KEY], model: m, maxretry: 2}
""",
    )
    codes = iter([429, 503, 200])
    calls: list[int] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        code = next(codes)
        calls.append(code)
        body = {"choices": [{"message": {"content": "ok"}}]} if code == 200 else {}
        return httpx2.Response(code, json=body)

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            return await llm.chat("x", providers=llm.load_providers(f), client=client)

    assert asyncio.run(run())[0] == "ok"
    assert calls == [429, 503, 200]


def test_retries_stop_at_maxretry_and_never_happen_for_auth_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(llm, "RETRY_BASE_S", 0)
    monkeypatch.setenv("R_KEY", "k")
    monkeypatch.setenv("A_KEY", "k")
    monkeypatch.delenv("LLM_FIRST", raising=False)
    f = _yaml(
        tmp_path,
        """
providers:
  - {name: auth, base_url: "https://auth.example/v1", keys: [A_KEY], model: m, maxretry: 3}
  - {name: rate, base_url: "https://rate.example/v1", keys: [R_KEY], model: m, maxretry: 2}
""",
    )
    hits: dict[str, int] = {"auth.example": 0, "rate.example": 0}

    def handler(req: httpx2.Request) -> httpx2.Response:
        hits[req.url.host] += 1
        return httpx2.Response(401 if req.url.host == "auth.example" else 429)

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            return await llm.chat("x", providers=llm.load_providers(f), client=client)

    with pytest.raises(llm.LLMError) as err:
        asyncio.run(run())
    assert hits == {"auth.example": 1, "rate.example": 3}  # 401: once; 429: 1 try + 2 retries
    assert "auth#1: 401" in str(err.value) and "rate#1: 429" in str(err.value)


def test_yaml_boolean_looking_names_are_rejected_with_a_clear_error(tmp_path) -> None:
    # unquoted on/off/yes/no parse as booleans in YAML 1.1; the validator must not accept them
    f = _yaml(tmp_path, "providers:\n  - {name: off, base_url: x, keys: [K], model: m}")
    with pytest.raises(llm.ConfigError, match="name"):
        llm.load_providers(f)


def test_extra_body_is_merged_into_requests_but_cannot_override_the_core_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("X_KEY", "k")
    monkeypatch.delenv("LLM_FIRST", raising=False)
    f = _yaml(
        tmp_path,
        """
providers:
  - name: x
    base_url: "https://x.example/v1"
    keys: [X_KEY]
    model: m
    extra_body: {chat_template_kwargs: {enable_thinking: false}}
""",
    )
    seen: dict = {}

    def handler(req: httpx2.Request) -> httpx2.Response:
        import json

        seen.update(json.loads(req.content))
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            return await llm.chat("x", providers=llm.load_providers(f), client=client)

    asyncio.run(run())
    assert seen["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["model"] == "m" and "messages" in seen
    bad = _yaml(
        tmp_path,
        "providers:\n  - {name: y, base_url: x, keys: [K], model: m, extra_body: {model: evil}}",
    )
    with pytest.raises(llm.ConfigError, match="extra_body"):
        llm.load_providers(bad)


# ---- cli providers (Claude Code / Codex style) -------------------------------------------------


def _cli_provider(tmp_path, code: str, *extra: str, **opts):
    import sys

    cmd = ", ".join(repr(x) for x in (sys.executable, "-c", code, *extra))
    fields = ", ".join(f"{k}: {v}" for k, v in {"maxretry": 0, "maxms": 5000, **opts}.items())
    f = _yaml(
        tmp_path,
        f"providers:\n  - {{name: fakecli, kind: cli, model: m1, command: [{cmd}], {fields}}}",
    )
    return llm.load_providers(f)


def test_cli_provider_gets_prompt_on_stdin_and_model_in_argv(tmp_path) -> None:
    provs = _cli_provider(
        tmp_path,
        "import sys; print('model=' + sys.argv[1] + ' got=' + sys.stdin.read())",
        "{model}",
    )
    text, used = asyncio.run(llm.chat("hello", "be brief", providers=provs))
    assert text == "model=m1 got=be brief\n\nhello"
    assert used == "fakecli/m1"


def test_cli_provider_never_sees_secrets_or_the_project_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "top-secret-value")
    monkeypatch.setenv("WEBSCRAPER_PG_PASSWORD", "another-secret")
    code = (
        "import os; "
        "print(sorted(k for k in os.environ if 'KEY' in k or 'PASSWORD' in k or 'SECRET' in k)); "
        "print(os.listdir('.')); print(os.getcwd())"
    )
    provs = _cli_provider(tmp_path, code)
    text, _ = asyncio.run(llm.chat("x", providers=provs))
    secrets_seen, listing, cwd = text.splitlines()
    assert secrets_seen == "[]"  # no API key or password reached the child
    assert listing == "[]"  # an empty scratch directory
    assert "llm-cli-" in cwd and cwd != os.getcwd()


def test_cli_timeout_kills_the_process_and_retries_only_timeouts(tmp_path) -> None:
    counter = tmp_path / "count.txt"
    code = "import sys, time; open(sys.argv[1], 'a').write('x'); time.sleep(30)"
    provs = _cli_provider(tmp_path, code, str(counter), maxms=400, maxretry=1)
    with pytest.raises(llm.LLMError) as err:
        asyncio.run(llm.chat("x", providers=provs))
    assert "fakecli: timeout" in str(err.value)
    assert counter.read_text() == "xx"  # one try plus one retry


def test_cli_crash_is_reported_once_and_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import sys

    counter = tmp_path / "count.txt"
    monkeypatch.setenv("NEXT_KEY", "k")
    f = _yaml(
        tmp_path,
        f"""
providers:
  - name: crashy
    kind: cli
    model: m
    maxretry: 3
    command:
      - {sys.executable!r}
      - -c
      - "import sys; open({str(counter)!r}, 'a').write('x'); sys.exit(3)"
  - {{name: nextone, base_url: "https://next.example/v1", keys: [NEXT_KEY], model: m}}
""",
    )

    def handler(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            return await llm.chat("x", providers=llm.load_providers(f), client=client)

    assert asyncio.run(run())[1] == "nextone/m"
    assert counter.read_text() == "x"  # an exit code is not retried, even with maxretry: 3


def test_missing_cli_binary_is_skipped(tmp_path) -> None:
    f = _yaml(
        tmp_path,
        "providers:\n"
        "  - {name: ghost, kind: cli, model: m, command: [definitely-not-installed-xyz]}",
    )
    provs = llm.load_providers(f)
    assert not provs[0].available
    with pytest.raises(llm.LLMError, match="ghost: definitely-not-installed-xyz not found"):
        asyncio.run(llm.chat("x", providers=provs))


def test_think_blocks_are_stripped_from_answers() -> None:
    assert llm.clean_answer("<think>\nreasoning here\n</think>\nParis") == "Paris"
    assert llm.clean_answer("<THINK>a</THINK>x<think>b</think>y") == "xy"
    assert llm.clean_answer("no tags") == "no tags"


def test_api_answer_with_think_block_is_cleaned(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("T_KEY", "k")
    f = _yaml(
        tmp_path,
        'providers:\n  - {name: t, base_url: "https://t.example/v1", keys: [T_KEY], model: m}',
    )

    def handler(req: httpx2.Request) -> httpx2.Response:
        content = "<think>\nthinking...\n</think>\n\nMachado de Assis."
        return httpx2.Response(200, json={"choices": [{"message": {"content": content}}]})

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            return await llm.chat("x", providers=llm.load_providers(f), client=client)

    assert asyncio.run(run())[0] == "Machado de Assis."


@pytest.mark.parametrize(
    "bad",
    [
        "providers:\n  - {name: a, kind: cli, model: m}",  # no command
        "providers:\n  - {name: a, kind: cli, model: m, command: [x], keys: [K]}",  # keys on a cli
        "providers:\n  - {name: a, kind: cli, model: m, command: [x], base_url: https://x}",
        "providers:\n  - {name: a, kind: cli, model: m, command: []}",
        # command on an api provider
        "providers:\n  - {name: a, base_url: x, keys: [K], model: m, command: [x]}",
        "providers:\n  - {name: a, kind: grpc, base_url: x, keys: [K], model: m}",
    ],
)
def test_cli_and_kind_validation(tmp_path, bad: str) -> None:
    with pytest.raises(llm.ConfigError):
        llm.load_providers(_yaml(tmp_path, bad))


def test_oauth_cli_providers_are_locked_down() -> None:
    by_name = {p.name: p for p in llm.load_providers()}
    claude, codex = by_name["claude"], by_name["codex"]
    assert claude.kind == codex.kind == "cli"
    argv = claude.argv()
    assert "--safe-mode" in argv  # no MCP servers, hooks or plugins in the child
    assert argv[argv.index("--tools") + 1] == ""  # no built-in tools
    assert "--bare" not in argv  # --bare skips the Keychain read and loses the OAuth login
    assert "--no-session-persistence" in argv
    assert not any(a in argv for a in ("--dangerously-skip-permissions", "--allowedTools"))
    cargv = codex.argv()
    assert ["-s", "read-only"] == cargv[cargv.index("-s") : cargv.index("-s") + 2]
    assert "--dangerously-bypass-approvals-and-sandbox" not in cargv and "--yolo" not in cargv
    assert not codex.enabled  # a read-only sandbox still lets it read files: off by default
