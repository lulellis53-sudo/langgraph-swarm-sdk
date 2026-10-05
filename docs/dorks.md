# Google dork tutorial

Build queries with `dork()` in
[`WebSearch/frontend/dorks.py`](../WebSearch/frontend/dorks.py), then pass them
to the WebSearch search helpers. See the
[pipeline guide](../WebSearch/PIPELINE.md) for supported entry points and
provider behavior.

A **dork** is a query that uses operators so Google returns a narrower set of pages.
This frontend always builds the same shape: one **parameter** OR-group, `AND`, one
**variable** OR-group, then optional site and date filters.

## Recipe

```text
(PARAMETER1|PARAMETER2|PARAMETER(X)) AND (VARIABLE1|VARIABLE2|VARIABLE3)
    (site:site1.com OR site:site2.com)
    after:YYYY-MM-DD before:YYYY-MM-DD
```

| Slot                                     | Required? | Meaning                                                                                                                   |
| ---------------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------- |
| `PARAMETER1\|PARAMETER2\|PARAMETER(X)`   | yes       | Family of _what_ you want. Add as many alternatives as you need (`X` = Nth). A page matching **any** parameter qualifies. |
| `AND`                                    | yes       | Both groups must match. Google already ANDs bare words; writing `AND` makes the two groups explicit.                      |
| `VARIABLE1\|VARIABLE2\|VARIABLE3`        | yes       | Synonyms or facets of the topic. A page matching **any** variable qualifies.                                              |
| `(site:site1.com OR site:site2.com)`     | optional  | Limit to one or more domains. Omit to search the open web.                                                                |
| `after:YYYY-MM-DD` / `before:YYYY-MM-DD` | optional  | Date window on last update. Use one bound, both, or neither.                                                              |

`|` is the same as the word `OR`. Groups must stay in parentheses so the `AND` applies to the whole set, not a single term.

## 1. Parameters — first group

Put every acceptable name for the **subject** in one OR-group.

```text
(PARAMETER1|PARAMETER2|PARAMETER3|PARAMETER4)
```

- One word stays bare: `langgraph`.
- Several words become an exact phrase: `"token budget"`.
- Do not put quotes, parentheses, or `|` _inside_ a single parameter (the builder rejects them).

```text
(langgraph|langchain|"langgraph swarm")
```

## 2. Variables — second group

Put every acceptable name for the **aspect** you care about, then join the two groups with `AND`.

```text
(PARAMETER1|PARAMETER2|PARAMETER(X)) AND (VARIABLE1|VARIABLE2|VARIABLE3)
```

```text
(langgraph|langchain) AND (handoff|swarm|"parallel agents")
```

That means: _(langgraph **or** langchain)_ **and** _(handoff **or** swarm **or** “parallel agents”)_.

You can add a third group the same way if you need another required facet:

```text
(langgraph|langchain) AND (handoff|swarm) AND (benchmark|eval)
```

## 3. Optional — sites

Restrict to domains **after** the required groups. No space after `site:`.

One site:

```text
(langgraph|langchain) AND (handoff|swarm) site:github.com
```

Several sites (any of them):

```text
(langgraph|langchain) AND (handoff|swarm) (site:github.com OR site:gitlab.com)
```

`site:` also accepts a host or URL prefix (`site:docs.python.org`, `site:https://docs.python.org/3/`).
A `site:` with a space (`site: github.com`) is **not** an operator — Google treats it as the word “site:”.

## 4. Optional — date window

Google’s `after:` / `before:` filter pages by last-update date. Combine them for a closed range.
This helper requires **ISO** `YYYY-MM-DD` (Google also accepts `YYYY` or `YYYY/MM/DD` if you type the query by hand).

```text
(langgraph|langchain) AND (handoff|swarm) after:2026-01-01 before:2026-12-31
```

| Form                                 | Effect                       |
| ------------------------------------ | ---------------------------- |
| `after:2026-03-10`                   | Updated on or after that day |
| `before:2026-11-01`                  | Updated before that day      |
| `after:2026-01-01 before:2026-06-30` | Inside the window            |
| omitted                              | No date filter               |

`after` must not be later than `before`.

## Full examples

Parameters + variables only:

```text
(pytest|unittest) AND ("flaky test"|"race condition")
```

- one site + lower date bound:

```text
(pytest|unittest) AND ("flaky test"|"race condition") site:github.com after:2026-01-01
```

- two sites + closed date window (the full recipe):

```text
(rfc|specification) AND (websocket|sse)
    (site:ietf.org OR site:w3.org)
    after:2026-01-01 before:2026-12-31
```

- extra operators this builder also emits:

```text
(rfc|specification) AND (websocket|sse) filetype:pdf intitle:draft -jobs after:2026-01-01
```

## Other operators

No space between the operator and its value.

| Operator             | Effect                   | Example                      |
| -------------------- | ------------------------ | ---------------------------- |
| `"…"`                | Exact phrase             | `"token budget"`             |
| `\|` or `OR`         | Either term              | `handoff\|swarm`             |
| `AND`                | Both sides               | `(a\|b) AND (c\|d)`          |
| `( )`                | Group an OR-set          | `(site:a.com OR site:b.com)` |
| `site:`              | One domain / URL prefix  | `site:github.com`            |
| `filetype:`          | Extension / content type | `filetype:pdf`               |
| `intitle:`           | Word in the title        | `intitle:changelog`          |
| `inurl:`             | Word in the URL          | `inurl:docs`                 |
| `-`                  | Exclude a term           | `-jobs`                      |
| `after:` / `before:` | Last-update window       | `after:2026-01-01`           |

Official references: [Refine Google searches](https://support.google.com/websearch/answer/2466433) and
[Search operators (Search Central)](https://developers.google.com/search/docs/monitor-debug/search-operators).

## Build with `dork()`

`dork()` quotes phrases, validates ISO dates, and rejects empty or illegal terms.
It does not touch the network.

```python
from WebSearch import dork, search_hits

q = dork(
    ["langgraph", "langchain"],          # (PARAMETER1|PARAMETER2|…)
    ["handoff", "swarm"],                # (VARIABLE1|VARIABLE2|…)
    site="github.com",                   # optional single site:
    after="2026-01-01",                  # optional after:
    before="2026-12-31",                 # optional before:
)
# '(langgraph|langchain) AND (handoff|swarm) site:github.com after:2026-01-01 before:2026-12-31'

hits = search_hits(q, limit=5)
```

Several sites: pass a ready group (string that already starts with `(`) so it is not re-quoted.

```python
q = dork(
    ["rfc", "specification"],
    ["websocket", "sse"],
    "(site:ietf.org OR site:w3.org)",
    after="2026-01-01",
    before="2026-12-31",
)
# '(rfc|specification) AND (websocket|sse) (site:ietf.org OR site:w3.org) after:2026-01-01 before:2026-12-31'
```

Other kwargs: `filetype=`, `intitle=`, `inurl=`, `exclude=["jobs", "forum"]` (each becomes `-term`).

## Common mistakes

| Wrong                                | Why                                | Right                                |
| ------------------------------------ | ---------------------------------- | ------------------------------------ |
| `site: github.com`                   | Space kills the operator           | `site:github.com`                    |
| `after:2026-mm-dd`                   | Placeholder is not a date          | `after:2026-03-10`                   |
| `after:2026-06-01 before:2026-01-01` | Window inverted                    | `after` ≤ `before`                   |
| `langgraph\|langchain AND swarm`     | `AND` binds tighter than you think | `(langgraph\|langchain) AND (swarm)` |
| `dork(["a\|b"])`                     | `\|` inside a term is rejected     | `dork(["a", "b"])`                   |

## Searcher caveats

Only Google fully honours every operator above. Brave, Exa, Tavily, and SearXNG
(DuckDuckGo / Bing) may treat `after:`, `AND`, or `|` as plain text, so the same
string is a _hint_ there, not a hard filter.

Use dorks only for public information you are entitled to look up. `dork()` never
opens a connection; it only returns a query string.
