# Optional Redis cache

Redis provides a shared exact cache for multiple Swarm or WebSearch processes. SQLite
remains the local semantic cache and fallback. With Redis unset, existing local behavior
continues.

## Enable

Install the optional client and configure a Redis URL in the process environment:

```sh
uv sync --extra redis
export REDIS_URL=redis://127.0.0.1:6379/0
```

For Swarm, `SWARM_REDIS_URL` is also accepted. Set `SWARM_REDIS_CACHE_TTL_S` to
change the default one-day response TTL. WebSearch uses its existing five-minute
search-result TTL; callers can override it through `cache_ttl_s`.

The service must be reachable from the application. This feature does not provision or
manage Redis.

## Cache behavior and resource limits

- Keys are SHA-256 digests under versioned `swarm:response` and
  `websearch:results` namespaces; full prompts and queries are not stored as key names.
- Values use compact UTF-8 strings / JSON, expire automatically, and are capped at
  256 KiB per entry.
- The Redis client uses a shared pool of at most eight connections and 100 ms connect
  and command timeouts.
- Redis errors are cache misses or ignored writes. Swarm continues through its SQLite
  exact and semantic cache; WebSearch uses its process-local search cache and then the
  provider on a miss.
- Swarm semantic lookup remains local. Redis only shares exact matches, avoiding
  embedding and vector-index work on Redis.

Redis stores cached agent responses, which may contain task output. Use a trusted Redis
service with appropriate access controls. For a server-wide memory ceiling, configure
the Redis service's own `maxmemory` and eviction policy; the client-side entry limit
does not impose a total server memory cap.

## Measure

Compare a repeated-query run with `REDIS_URL` unset against one with Redis configured.
Record p50/p95 cache lookup latency, provider calls avoided, Swarm model tokens avoided,
process CPU time, and peak RSS. Include cold misses and warm hits separately. Redis is
useful for cross-process reuse; a local in-process hit can be faster for a single worker.
