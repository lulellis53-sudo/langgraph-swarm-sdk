# SniperSearch task — search the catalog, store today's findings

Goal: search today's offers for every product in the hardware catalog using
`SniperSearch.py`, parse BRL prices, and write every plausible finding into
the databases (SQLite observations + day-partitioned Parquet).

## Workflow

```text
                 +---------------------------+
                 | hardware.yaml  (inputs)   |
                 | . products: sku/terms/specs
                 | . sources:  site: domains |
                 | . plausible: BRL guards   |
                 +-------------+-------------+
                               |
                               v
                 +---------------------------+
                 | load_catalog()            |
                 | 30 SKUs -> search plan    |
                 +-------------+-------------+
                               |
                               v
   after:YYYY-MM-DD before:+1d   +---------------------+
   +--------------------+        | ProviderConfig      |
   | SniperSearch       |<-------| . backends ddg/exa  |
   | . window()         |        | . limit / timeout   |
   | . dork()           |        | . fresh=True        |
   | @sniper.function() |        +---------------------+
   | sniper.call(name)  |
   +---------+----------+
             | live hits (url, title, snippet)
             v
   +---------------------+     fail -> continue, report,
   | parse_brl_cents()   |     never retry twice
   | title + snippet     |
   +---------+-----------+
             | price in BRL
             v
   +-----------------------------+
   | plausible_brl range filter  |
   | in range  -> keep           |
   | no price  -> priceless row  |
   | outside   -> discard        |
   +---------+-------------------+
             | validated records (specs from catalog)
             v
   +----------------------+    +---------------------------+
   | offers.db (SQLite)   |    | Database/<Month>/DAY<d>/  |
   | import_observation() |    | append_products() Parquet |
   | bound parameters     |    | product.schema.json       |
   +----------+-----------+    +------------+--------------+
              |                             |
              +-------------+---------------+
                            v
              +---------------------------+
              | report: per SKU           |
              | hits / stored / best price|
              +---------------------------+
```

## Inputs (the yaml files)

- `Prediction/BotDeal/hardware.yaml` — single source of truth:
  - `products:` SKUs, names, categories, search `terms`, optional `specs`
    (branch/model, e.g. `B650`, `B850`).
  - `sources:` the sites to scope searches to (`site:` domains).
  - `plausible:` BRL ranges; prices outside the range are misparses and are
    discarded, never stored.
- Runtime note: the pipeline modules resolve from the Swarm lane checkout.

## Environment

```sh
cd /Users/usuario/Myworkspace/BotDeal
PYTHONPATH="/Users/usuario/Myworkspace/Swarm:/Users/usuario/Myworkspace/Swarm/src:/Users/usuario/Myworkspace/BotDeal" \
  /Users/usuario/Myworkspace/NSFW/ScoreMeter/.venv/bin/python <script or -c>
```

## Task steps

1. **Load the catalog** with `Prediction.BotDeal.hardware.load_catalog()`
   (it reads the yaml; never hardcode SKUs in the search script).
2. **Configure SniperSearch** with `ProviderConfig(backends=("ddglite", "exa"),
   fresh=True)` and `sniper.window(after=<today>, before=<today+1>)`.
3. **Register one search function per source kind** with
   `@sniper.function()` (retailers, marketplaces, communities) and call
   them via `sniper.call(...)` — one query per product per source group,
   terms taken from the catalog.
4. **Parse prices** with `Prediction.harvest.parse_brl_cents(text) / 100`
   from title and snippet; keep only hits inside the product's
   `plausible_brl` range. Hits without a parseable price are recorded as
   priceless rows, never guessed.
5. **Store findings** (today's `observed_at` only):
   - SQLite observations: `Prediction.br_hardware.connect(db_path)` +
     `import_observation(...)` — arguments are bound parameters; never
     assemble SQL strings.
   - Parquet: `Prediction.BotDeal.database.append_products(records,
     month=..., day=...)` — records validated against
     `Prediction/BotDeal/product.schema.json`, including `specs` from the
     catalog. The Parquet root is `Swarm/Prediction/Database/<Month>/DAY<d>/`.
6. **Report**: per SKU — hits seen, plausible findings stored, best price.

## Rules

- Never store prices outside the plausible range; never invent a price.
- Never commit: `offers.db`, `Database/`, `.env`, or any key. Bot token
  stays in the Keychain (`TELEGRAM_BOT_TOKEN`); secrets never in code or logs.
- Respect the search stack's politeness: keep `--limit` small, use
  `fresh=True` only when today's results are actually needed.
- If a search backend fails, continue with the others and report the
  failures; do not retry a failing backend more than once.
- Quick alternative when per-source grouping is not needed:
  `python -m Prediction.BotDeal.harvest_run --skus <skus> --days 1 --fresh
  --db <path>/offers.db` does steps 3–5 in one pass.
