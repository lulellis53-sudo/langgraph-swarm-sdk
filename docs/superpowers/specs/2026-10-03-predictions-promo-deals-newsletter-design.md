# PromoDeals and TechNewsletter Predictions Design

> Status: design for review  
> Date: 2026-10-03  
> Scope: PromoDeals / newsletter data pipeline on `feat/prediction-engine` under `Prediction/` (merged with the mlforecast engine).

## Goal and agreed requirements

Build a daily, auditable data foundation for a Portuguese tech-deals blog and a technology newsletter. The system records verified hardware offers, computes daily price floors and historical forecasts, identifies unusually low prices, and produces cited drafts for human review. It also produces a separate interest signal for newsletter topics. Synthetic data supports development and demonstrations but must never be mistaken for observed market data.

The tracked deal categories are NVIDIA RTX 5000-series GPUs, DDR5 memory, AMD Ryzen AM5 CPUs, and 1 TB PCIe 4.0 SSDs. Requested discovery sources are KaBuM, Terabyte, Magalu, Pichau, Amazon Brasil, OLX, X, Promobit, and Pelando.

## Architecture

Extend the `Prediction/` package (forecast engine + offer pipeline) on the prediction-engine worktree, separate from the sibling `Newsletter/` worktree. Use one SQLite database shared by the deal and newsletter submodules. `ForecastEngine` is called through a narrow adapter in `Prediction/br_hardware.py`; the initial database and daily calculations do not require a new forecasting dependency.

### Components

- `Prediction/storage.py`: SQLite connection setup, schema initialization, transactions, and repository operations shared by both product areas.
- `Prediction/synthetic.py`: deterministic fixtures for products, source listings, daily prices, and topic signals. Each generated record is explicitly tagged `synthetic`; the seed is isolated from real observations and purchase alerts.
- `Prediction/PromoDeals/`: category/catalog definitions, search-query generation, verified offer ingestion, daily price-floor calculations, historical threshold alerts, and deal predictions.
- `Prediction/TechNewsletter/`: daily topic-interest signals, short horizon forecasts, and reproducible article-draft records with citations and data cutoff.
- A CLI entry point (command name finalized in the implementation plan) runs schema setup, synthetic seeding, daily collection/import, calculations, alert creation, and draft generation as explicit subcommands.

Keep `Newsletter/` unchanged; reuse its offline digest conventions only if they fit without importing its worktree implementation.

## Data flow

1. Generate daily Google search dorks per configured product/source and date window. Keep the human-readable query in the database and safely URL-encode it when a search URL is constructed. Generate a broad query and a coupon-oriented variant using `(CUPOM OR CODIGO OR PROMO OR %OFF)` so coupon terms do not suppress otherwise useful discovery results. Example date window: `after:2026-10-02 before:2026-10-04`.
2. Treat search results as leads only. An operator confirms the landing page and records the observed price, timestamp, product identity, condition, payment method, shipping when available, coupon terms, source, and evidence URL. Initially accept a manual CSV/CLI import or manual entry. Automated collection may be added only through an official, authorized API and must respect its eligibility and terms.
3. Normalize product identity while preserving listing/source identity. Keep new and used goods separate. Keep Pix and card prices as distinct observations; do not silently compare one payment mode against another. Exclude unverified, stale, synthetic, or incomplete prices from real daily floor calculations.
4. For each category/product and date, store the lowest eligible verified price and the observation count. Preserve all source observations so the floor can be reproduced.
5. Compute deal alerts against the prior 30 calendar days of valid daily floors, excluding the current day. Require at least five prior daily floor values. Alert when today’s floor is less than or equal to 70% of the prior-window median (30% or more below it). Store the baseline sample count, median, threshold, and calculation date with the alert. Missing or insufficient history yields no alert.
6. Produce 7-day and 30-day price-trend predictions with model/version, training cutoff, inputs, and uncertainty metadata. Newsletter topic-interest signals use dated source observations and the same cutoff discipline. Forecasts are advisory and must not be presented as confirmed events.
7. Save article drafts as versioned records with cited source URLs, cited observation IDs, generated date, data cutoff, forecast horizon, and uncertainty. Drafts require human review and are never published automatically.

Google’s `after:` and `before:` operators filter search results by last-updated date; they do not prove when a price was offered or that it is still available. Therefore, a search-result snippet alone cannot become a verified price.

## Source policy

Separate retailer/marketplace sources from community/social discovery sources. Store source type, authorization/method, and evidence per observation. Search-engine dorks support discovery, not automated extraction. Default ingestion remains manual. Add an API connector only when the source explicitly provides an authorized route for this use and the account/eligibility requirements are met. Do not scrape sites whose applicable terms prohibit bots, crawlers, or extraction without consent. Any source that cannot be collected under an authorized method remains a manually confirmed lead or is disabled.

## Storage model

SQLite is the initial local store. Use foreign keys, uniqueness constraints for idempotent imports, and UTC timestamps alongside the market date in `America/Sao_Paulo`. The schema should cover:

- `products`: canonical name, category, manufacturer/model identifiers, key specs, and new/used eligibility.
- `sources`: source name, source class, ingestion method, authorization notes, and enabled state.
- `search_runs`: date window, exact query text, source/product target, run timestamp, and result metadata.
- `listings`: source listing identity, canonical product link, URL, condition, and first/last seen timestamps.
- `price_observations`: listing, observed time/date, amount/currency, payment method, shipping, coupon, verification status, evidence, and `data_origin` (`observed` or `synthetic`).
- `daily_price_floors`: product/category, market date, payment method, floor, eligible observation count, and provenance.
- `deal_alerts`: current floor, baseline median/window/count, threshold, and alert state.
- `topic_signals`: topic, date, source, measured value, evidence, and origin.
- `predictions`: target, horizon, model/version, generated time, cutoff, point/band estimate, uncertainty, and origin.
- `article_drafts`: versioned title/body, citations, linked predictions/observations, cutoff, review status, and origin.

Synthetic rows must carry their origin through derived floors, signals, predictions, and drafts. Synthetic-derived output is visibly labeled and is ineligible for real purchase alerts or claims about observed current prices.

## Failure handling and reproducibility

A failed search or import must not erase prior observations. Store collection/import errors with run metadata; rerunning the same import should be idempotent. Reject malformed prices, unknown payment modes, missing evidence for a verified real offer, and invalid date windows with actionable errors. Calculations must be repeatable from stored inputs, calculation version, and cutoff. If the forecasting backend is unavailable or history is insufficient, persist the observed statistics and mark the forecast unavailable rather than fabricating a prediction.

## Validation requirements

- Deterministic synthetic seeding with strict origin labels and no alert contamination.
- Idempotent import and listing/product deduplication without merging distinct offers.
- Correct treatment of new versus used items, Pix versus card, shipping, and coupon data.
- Exact threshold behavior at 70% of baseline median; no alert above threshold.
- Exclusion of current-day values from the prior 30-day baseline and minimum of five prior daily points.
- Dork generation for all configured sources/categories, both broad and coupon variants, correct `after`/`before` boundaries, and URL-safe encoding of `%`.
- Temporal leakage checks: forecasts and article drafts cannot use observations after their stored cutoff.
- Article citations resolve to stored evidence; generated drafts remain pending human review.
- Database initialization and daily operation work without network access when using synthetic data or imported observations.

## Explicit non-goals

- Automatically purchasing products, posting alerts externally, or publishing blog/newsletter content.
- Treating synthetic data as market evidence.
- Building a web UI or production hosted service in this iteration.
- Unapproved web scraping or depending on Google Custom Search JSON API for new integration.
- Claiming that a trend forecast predicts a definite future event.

## Research references

These references inform source discovery and the initial authorization boundaries; verify current terms and API availability when implementing each connector.

1. [Google Search operators](https://support.google.com/websearch/answer/2466433?hl=en-029) — date operators are discovery filters, not offer verification.
2. [Google Custom Search JSON API overview](https://developers.google.com/custom-search/v1/overview?authuser=531&hl=en) — the API is closed to new customers and has a published support sunset, so it is not a foundation for new ingestion.
3. [Amazon Creators API onboarding](https://associados.amazon.com.br/creatorsapi/docs/en-us/onboarding/register-for-creators-api) — API access has program eligibility requirements.
4. [X recent post search](https://github.com/xdevplatform/docs/blob/main/x-api/posts/search/introduction) — recent-post search covers a limited rolling time range.
5. [Magalu Products API](https://developers.magalu.com/docs/apis/products/overview/index.html) — documented product API is oriented around seller catalog operations.
6. [Terabyte partner program terms](https://www.terabyteshop.com.br/site/regras-programa-de-parceiros) — partner terms govern permitted program use and collection.
7. [Promobit terms](https://www.promobit.com.br/institucional/termos/) — terms constrain bots/crawlers and extraction.
8. [Pelando terms](https://www.pelando.com.br/sobre/termos-de-uso) and [Creator program](https://www.pelando.com.br/seja-um-creator) — use only an explicitly permitted route.
9. [OLX terms of use](https://ajuda.olx.com.br/s/article/termos-e-condicoes-de-uso) — automated collection must follow current terms.
