# GoogleDork.MD — deal-hunting dork tutorial for the BotDeal stack

How to build Google-style dorks that find **today's** hardware deals on the
tracked Brazilian sources, and how to run them through `SniperSearch.py`.

## Anatomy of a deal dork

```text
(PRODUCT1 | PRODUCT2) (CUPOM OR CODIGO OR DESCONTO OR PROMO OR %OFF OR PIX) (site1 | site2 | siteN) after:YYYY-MM-DD before:YYYY-MM-DD
```

| Block | Meaning | Notes |
| --- | --- | --- |
| `(PRODUTO1 | PRODUTO2)` | product names/spellings, OR-grouped | Quote multi-word names: `"rtx 5070 ti"`. Always add the PT spelling your buyers search. |
| `(CUPOM OR CODIGO OR ...)` | deal-intent words | Deal pages almost always contain one of these. `PIX` catches "no PIX" cash discounts. `%OFF` also matches "10% off". |
| `(site1 | site2 | siteN)` | source scope | Keep each `site:` inside the same parenthesis group, e.g. `(site:kabum.com.br | site:pichau.com.br)`. |
| `after: before:` | freshness window | `after:today` is written as a real date: `after:2026-10-11 before:2026-10-12`. Google treats dates as inclusive-start / exclusive-end in practice — window = that single day. |

Rules that save runs:

- Google's default operator between blocks is AND — you do **not** write the word `AND`.
- `OR` must be uppercase (or use `|`). Lowercase `or` is ignored.
- Minus-excludes prune noise: `-usado -seminovo` kills used-item listings.
- Too narrow (0 results)? Drop the `site:` block first, then widen `after:`.
- The pipeline's own builder is `Prediction.BotDeal.discovery.product_dork()`;
  hand-written dorks like the ones below are for interactive use and for
  `SniperSearch.search(..., raw_dork=True)`.

## The 5 templates

Replace `PRODUTO`, the `site:` list and the dates. All templates assume
"today" = `2026-10-11` (swap in the real day).

### 1. Today's coupon for one product, all tracked retailers

```text
("rtx 5070 ti") (CUPOM OR CODIGO OR DESCONTO OR PROMO OR %OFF OR PIX) (site:kabum.com.br | site:terabyteshop.com.br | site:pichau.com.br | site:amazon.com.br | site:magazineluiza.com.br | site:casasbahia.com.br) after:2026-10-11 before:2026-10-12
```

Best first query for any single SKU: one product, deal words, every
retailer, today only.

### 2. Price-drop watch across two product generations

```text
("rtx 5060" | "rtx 5060 ti") (PROMO OR DESCONTO OR %OFF OR PIX) (site:kabum.com.br | site:pichau.com.br | site:mercadolivre.com.br) after:2026-10-10 before:2026-10-12
```

48-hour window; use when a launch/holiday week makes prices move daily and
you want yesterday's drops too.

### 3. Memory-kit cash discount (PIX)

```text
("kit ddr5 32gb" | "ddr5 2x16gb") (PIX OR CUPOM OR CODIGO) (site:kabum.com.br | site:terabyteshop.com.br | site:pichau.com.br) -usado -seminovo after:2026-10-11 before:2026-10-12
```

PIX-only intent plus used-listing exclusion — the memory market's noisiest
corner. Same shape works for `ddr4`.

### 4. Motherboard bundle (board + CPU bought together)

```text
("placa mae b650" | "b650" | "b850") (KIT OR COMBO OR PROMO OR CUPOM) (site:kabum.com.br | site:pichau.com.br | site:terabyteshop.com.br) after:2026-10-11 before:2026-10-12
```

`KIT`/`COMBO` are the words Brazilian shops use for board+CPU bundles;
unquoted `b650` catches titles that spell the chipset alone.

### 5. Community/promo aggregators (Promobit, Pelando, X)

```text
("rtx 5080" | "ryzen 7 9800x3d") (PROMO OR CUPOM OR DESCONTO OR CUPOM DESCONTO) (site:promobit.com.br | site:pelando.com.br | site:x.com) after:2026-10-11 before:2026-10-12
```

Aggregators surface minor-shop deals the retailer-scoped queries miss;
expect reposts, so dedupe by URL before storing.

## Running a template through SniperSearch

```python
from SniperSearch import ProviderConfig, SniperSearch

sniper = SniperSearch(providers=ProviderConfig(backends=(), limit=10, fresh=True))
sniper.window()  # dates are already in the raw dork; keep the instance's own window empty

@sniper.function(description="Template 1: today's RTX 5070 Ti coupons")
def t1(s: SniperSearch) -> list[dict[str, str]]:
    return s.search('("rtx 5070 ti") (CUPOM OR CODIGO OR DESCONTO OR PROMO OR %OFF OR PIX) '
                    "(site:kabum.com.br | site:terabyteshop.com.br | site:pichau.com.br) "
                    "after:2026-10-11 before:2026-10-12", raw_dork=True)

for hit in sniper.call("t1"):
    print(hit["url"], hit["title"][:60])
```

Store the results through the normal path
(`Prediction.BotDeal.database.append_products`) so they land in
`Database/<Month>/DAY<d>/` with `specs` and schema validation — the full
procedure is in `SniperSearch.AGENTS.md`.
