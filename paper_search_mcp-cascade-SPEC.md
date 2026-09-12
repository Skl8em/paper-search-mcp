# `paper-search-mcp` — citation cascade fork

**Status**: specification, not yet started.
**Validity phase**: written against `paper-search-mcp` 0.1.4. If the installed version differs, re-verify §4 before acting.
**Verification stamp**: every claim tagged `[Verified 2026-09-12]` was executed against the live API or the installed source on that date. Claims tagged `[To verify]` were not — check them before relying on them.

---

## 0. What this project is

A fork of [`openags/paper-search-mcp`](https://github.com/openags/paper-search-mcp) (MIT) that adds **bidirectional citation traversal** — backward (what a work cites) and forward (what cites a work) — which the upstream package does not expose through any of its 21 backends.

The deliverable is a locally-installed MCP server, replacing the upstream `uv tool` install, that keeps every existing tool working and adds citation-graph tools on top.

---

## 1. Why this exists

The `cascade-literature-review` skill is built around a recursive citation cascade: seed corpus → backward references → forward citers → repeat to fixed point. That method requires traversing the citation graph in both directions.

`paper-search-mcp` 0.1.4 cannot do it. Verified by grepping every adapter in `academic_platforms/` for reference-list and citing-work handling: **none requests them**. The Semantic Scholar adapter reads only `citationCount` (`semantic.py:140`). No adapter requests OpenAlex's `referenced_works`, Crossref's `reference` array, or any `/citations` endpoint. `[Verified 2026-09-12]`

The sharp detail that shapes the whole fix:

> `paper_search_mcp/paper.py` — the `Paper` dataclass **already declares `references: Optional[List[str]] = None`**, `__post_init__` defaults it to `[]`, and `to_dict()` already serializes it as `'; '.join(self.references)`. `[Verified 2026-09-12]`

So the field exists, is plumbed end-to-end, and is simply never written to. That is why every MCP search result comes back with `"references": ""`. **This is a population problem, not a schema-extension problem** — the data model needs no change for the backward direction. Forward citation is genuinely new surface area, because a citing-works list is not a property of the `Paper` being described.

---

## 2. Why fork rather than send a PR upstream

Upstream repo state: **2.6k stars, 50 commits on `main`, 23 open issues, 37 open pull requests.** `[Verified 2026-09-12, via GitHub repo page]`

Thirty-seven open PRs against fifty total commits is the decisive number. Merge throughput, not patch quality, is the bottleneck; a PR is likely to sit indefinitely. Forking is therefore the realistic path to a working tool, not the impatient one.

Second reason, independent of the first: the package is installed as a `uv` tool at
`/Users/bnc/.local/share/uv/tools/paper-search-mcp/lib/python3.14/site-packages/paper_search_mcp/`.
Editing `site-packages` in place **works until the next `uv tool upgrade`, which silently discards it.** Any durable change must live in a real source tree installed from a local path. `[High confidence — standard uv tool semantics; not empirically destroyed on 2026-09-12]`

**Still send the PR** once the fork works. Costs one command, and a merge removes the maintenance burden. Just don't make the fork's usefulness contingent on it.

---

## 3. Why OpenAlex primary, OpenCitations as cross-check, Semantic Scholar excluded from the backward path

This is the load-bearing design decision. It is empirical, not a preference.

Test paper throughout: **Allingham & Sandmo 1972, _Income tax evasion: a theoretical analysis_**, `doi:10.1016/0047-2727(72)90010-2`, OpenAlex `W2088435028`. Chosen because it is canonical in the tax-compliance literature and old enough to stress index coverage.

| Source | Backward | Forward | Auth |
|---|---|---|---|
| OpenAlex | ✅ `referenced_works` → 6 IDs | ✅ `filter=cites:` → ~4959 | none |
| OpenCitations | ✅ OCI records w/ timespan | ✅ count 2919 | none |
| Semantic Scholar | ❌ **`"data": null`** | ✅ works | optional key |

`[All three Verified 2026-09-12]`

### 3.1 Semantic Scholar is structurally unfit for backward traversal

`GET /graph/v1/paper/DOI:10.1016/0047-2727(72)90010-2/references` returned `"data": null` with this notice:

> `Notice: The following paper fields have been elided by the publisher: {'references'}`

`[Verified 2026-09-12 — quoted verbatim from the live response]`

The publisher suppressed the reference list. This is not rate limiting and **no API key fixes it**. Elsevier holds a large share of economics journals, so this failure lands precisely on the corpus of interest. Forward citations from S2 were unaffected and returned 2026 papers normally.

Consequence for design: **never make S2 the backward source.** It may serve as a forward supplement.

### 3.2 The indices disagree with each other — and with themselves

Forward citation count for the same paper: **OpenAlex 4959, OpenCitations 2919.** A ~40% divergence.

Worse, OpenAlex is internally inconsistent: the `cited_by_count` field returns **4947** while `filter=cites:W2088435028` reports **4959**. `[Verified 2026-09-12, two calls minutes apart]`

And OpenAlex reports **only 6** `referenced_works` for a 1972 paper whose printed bibliography is certainly longer — pre-digital reference lists are poorly captured.

**This is not a bug to fix. It is a property of the domain, and the tool must surface it rather than hide it.** A cascade's "exhaustiveness" is a property of the chosen index, not of the literature. Two implications that are requirements, not nice-to-haves:

- Any tool returning a citation count MUST label which index produced it.
- Cross-source disagreement MUST be reportable, not silently merged away. An agent running a cascade needs to be able to state "backward coverage for pre-1980 work is weak in this index" in its output.

---

## 4. Current state of the code — verified facts

Installed package root:
`/Users/bnc/.local/share/uv/tools/paper-search-mcp/lib/python3.14/site-packages/paper_search_mcp/`

| Path | Relevant content |
|---|---|
| `paper.py` | `Paper` dataclass. Has unused `references` field + `to_dict()` serialization. |
| `academic_platforms/base.py` | `PaperSource(ABC)`. **Only `search()` is `@abstractmethod`**; `download_pdf`/`read_paper` are concrete and raise `NotImplementedError`. Adding new methods to subclasses breaks nothing. |
| `academic_platforms/openalex.py` | `OpenAlexSearcher`. 188 lines. `BASE_URL = "https://api.openalex.org/works"`. Primary edit target. |
| `config.py` | `get_env(name)` → reads `PAPER_SEARCH_MCP_<name>` then `<name>`, loading `~/.config/paper-search-mcp/.env`. `ENV_PREFIX = "PAPER_SEARCH_MCP_"`. Use this for any new config. |
| `server.py` | 63 `@mcp.tool` registrations; 57 active, 6 gated behind `IEEE_API_KEY`/`ACM_API_KEY`. `ALL_SOURCES` list at ~line 75. `search_papers` aggregator at line 243. |

`[All Verified 2026-09-12]`

Dependencies (`Requires-Python: >=3.10`): `beautifulsoup4>=4.12.0`, `fastmcp`, `feedparser`, `httpx[socks]>=0.28.1`, `lxml>=4.9.0`, `mcp[cli]>=1.6.0`, `pypdf`, `requests`; `pytest>=8.0` under `dev` extra. **`pytest` is already a declared dev dependency and `tests/` exists upstream** — so the TDD loop needs no new tooling. `[Verified 2026-09-12]`

### 4.1 A latent bug to fix while in there

`openalex.py:21` hardcodes:

```python
{"User-Agent": "paper-search-mcp/1.0 (mailto:openags@example.com)"}
```

Every user of this package enters OpenAlex's "polite pool" under a **fake email belonging to the upstream maintainer**. That is both impolite and a shared-fate rate-limit risk. Replace with `get_env("OPENALEX_EMAIL", "")` and omit the `mailto` entirely when unset. `[Verified 2026-09-12 — read from source]`

---

## 5. Scope

### In scope

New tools on the OpenAlex adapter:

1. **`get_work_references(work_id)`** — backward. Resolve `referenced_works` IDs to full `Paper` objects. Must populate `Paper.references` on the seed work.
2. **`get_work_citations(work_id, max_results, cursor)`** — forward, via `filter=cites:<id>`. Must paginate; 4959 citers is a normal case.
3. **`resolve_work(identifier)`** — accept DOI, OpenAlex ID, or bare URL; return the canonical OpenAlex work ID. Every other tool depends on this normalization.
4. **`cross_check_citations(doi)`** — query OpenAlex *and* OpenCitations for the same work, return both counts plus their delta. This is the §3.2 requirement made executable.

Supporting work:
- OpenCitations adapter (new file `academic_platforms/opencitations.py`) — no auth, `references`/`citations`/`citation-count` endpoints.
- Populate `Paper.references` in `OpenAlexSearcher.search()` so ordinary searches stop returning `""`.
- Configurable `OPENALEX_EMAIL` (§4.1).

### Out of scope

- Multi-hop cascade orchestration / fixed-point logic. The MCP server exposes **one hop**; recursion belongs in the skill, not the server. Keeps the tool dumb and the method inspectable.
- Graph visualization.
- Fixing `pubmed` (NCBI non-XML), `ssrn` (403 bot detection), `base` (silent empty), `dblp` (XML parse error), `citeseerx` (dead endpoint). All verified broken 2026-09-12, all unrelated to this fork's purpose.
- IEEE/ACM connectors.
- Semantic Scholar backward references — excluded by §3.1.

---

## 6. TDD plan — write these first, in this order

Red → green → refactor. No implementation ahead of a failing test.

### Test 1 — the bidirectional fixture (the contract the whole cascade rests on)

This pair was verified in both directions on 2026-09-12 and is the anchor fixture:

- **Backward**: `W2088435028`'s `referenced_works` contains `W2084610231`.
- **Forward**: `filter=cites:W2084610231` includes `W2088435028` (246 total citers; found within the first 200).

```
assert "W2084610231" in get_work_references("W2088435028").ids
assert "W2088435028" in get_work_citations("W2084610231").ids
```

Both directions must agree about the same edge. If one passes and the other fails, the ID normalization in `resolve_work` is wrong — that is the single most likely defect.

`W2084610231` is `doi:10.2307/2552162`. **OpenCitations independently confirms this same edge**, returning `cited: omid:br/0610462181 doi:10.2307/2552162 openalex:W2084610231` for the same citing work. So the fixture is cross-validated across two independent indices — use it for the OpenCitations adapter too. `[Verified 2026-09-12]`

### Test 2 — `Paper.references` is actually populated

Regression guard for the §1 finding. After `search("income tax evasion")`, at least one returned `Paper` must have a non-empty `references` list, and `to_dict()["references"]` must not be `""`.

### Test 3 — pagination is real

`get_work_citations("W2088435028")` must be able to retrieve more than 200 results. OpenAlex caps `per_page` at 200 and the paper has ~4959 citers, so a single-page implementation silently truncates at 4%. Assert that requesting 250 yields 250 distinct IDs.

> Use OpenAlex cursor paging (`cursor=*`, then the `meta.next_cursor` from each response) rather than `page=`, which is capped for deep result sets. **`[To verify]` — I did not exercise cursor paging on 2026-09-12; confirm the parameter name and the `meta.next_cursor` field against the live API before building on it.**

### Test 4 — never assert exact counts

A test asserting `count == 4959` will break, possibly within the hour — OpenAlex returned 4947 and 4959 for the same paper minutes apart (§3.2). Assert **magnitude and structure** instead: `count > 4000`, `len(ids) == requested`, no duplicate IDs, every ID matches `^W\d+$`.

Write this as an explicit test-design note in the test file. Its absence is how the suite rots.

### Test 5 — graceful degradation, loudly

Per the engineering contract's fail-loud rule, and because upstream's existing failure mode is the opposite (`base` and `unpaywall` both return `[]` with no error):

- A work with genuinely zero `referenced_works` must return an empty result **distinguishable from an error**.
- An unresolvable identifier must raise, not return `[]`.
- An OpenCitations 5xx must surface as an error on the OpenCitations field of `cross_check_citations` while the OpenAlex field still returns its value. Partial success must be visible as partial.

---

## 7. Implementation notes

### 7.1 Verified endpoint reference

All executed 2026-09-12. Append `&mailto=<your email>` for the polite pool.

```
# Backward — returns full OpenAlex IDs as URLs
GET https://api.openalex.org/works/W2088435028?select=referenced_works
  → {"referenced_works": ["https://openalex.org/W1991069915", ... 6 total]}

# Forward — note meta.count
GET https://api.openalex.org/works?filter=cites:W2088435028&per-page=200&select=id
  → {"meta": {"count": 4959}, "results": [{"id": "https://openalex.org/W..."}]}

# DOI → work (DOI passed as a full URL in the path)
GET https://api.openalex.org/works/https://doi.org/10.1016/0047-2727(72)90010-2

# OpenCitations — MUST follow redirects, see 7.3
GET https://opencitations.net/index/api/v2/references/doi:<doi>
GET https://opencitations.net/index/api/v2/citations/doi:<doi>
GET https://opencitations.net/index/api/v2/citation-count/doi:<doi>
  → [{"count": "2919"}]   # note: count is a STRING, not an int
```

Two parsing gotchas, both verified:
- OpenAlex IDs come back as **full URLs** (`https://openalex.org/W...`). Existing code at `openalex.py:76` already strips this prefix — reuse that convention, do not invent a second one.
- OpenCitations `citation-count` returns the count as a **quoted string** inside a single-element array. Cast explicitly; do not trust it to be numeric.

### 7.2 `select=` is your rate-limit budget

The current `search()` (`openalex.py:57-60`) sends no `select`, so it downloads full records including `abstract_inverted_index` — a large payload per work. For a cascade fetching thousands of citers this dominates both time and quota. Always send a minimal `select` on traversal calls. Reconstructing abstracts is only needed for works the user will actually read.

`[Rate limits: OpenAlex publishes per-day and per-second caps. To verify — do not code a limiter against remembered numbers; read https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication first.]`

### 7.3 OpenCitations redirects

`https://opencitations.net/index/api/v2/...` returned **HTTP 301** on first request. With `requests`, `Session.get` follows redirects by default, but confirm it in the adapter rather than assuming — a non-following client gets a 17-byte body and silently reports zero references. This is exactly the failure class §6 Test 5 exists to catch. `[Verified 2026-09-12 — 301 observed; 200 with body after following]`

### 7.4 Don't fight the ABC

`PaperSource` requires only `search()`. Add `get_references()` / `get_citations()` as plain methods on `OpenAlexSearcher` and the new `OpenCitationsSearcher`. **Do not** add them as `@abstractmethod` on the base class — that would break all 20 other adapters, none of which can implement them. `[Verified 2026-09-12 — base.py read in full]`

### 7.5 Registering tools in `server.py`

Follow the existing `@mcp.tool` pattern. Note the conditional-registration idiom at `server.py:112-130` (IEEE/ACM gated on a key) — the new tools need no key and should register unconditionally. Add `"opencitations"` to `ALL_SOURCES` only if you also give it a working `search()`; if it is traversal-only, leave it out, because `_parse_sources` feeds `ALL_SOURCES` straight into the `search_papers` aggregator and a searcher without `search()` will throw there.

---

## 8. Setup

```sh
gh repo fork openags/paper-search-mcp --clone
cd paper-search-mcp
uv sync --extra dev
uv run pytest                      # establish the baseline BEFORE changing anything
```

Record which upstream tests already fail on a clean checkout. Given 21 network-dependent backends and five verified-broken ones (§5), **assume the baseline is not green** and do not mistake a pre-existing failure for one you caused.

Swap the installed tool for the fork once tests pass:

```sh
uv tool uninstall paper-search-mcp
uv tool install --editable /path/to/paper-search-mcp
```

Then re-point the MCP registration at it. The current entry is `paper-search-mcp` → `/Users/bnc/.local/bin/paper-search-mcp` (stdio). `[Verified 2026-09-12 via claude mcp list]`

---

## 9. Acceptance criteria

1. §6 Tests 1–5 pass.
2. All 57 pre-existing tools still register and the previously-working 15 backends still return results — the fork must not regress what worked.
3. `get_work_references` and `get_work_citations` resolve the anchor fixture in both directions.
4. `search()` populates `Paper.references`; `to_dict()["references"]` is non-empty for works that have them.
5. Forward traversal retrieves >200 results without truncation.
6. `cross_check_citations` reports the OpenAlex/OpenCitations delta rather than collapsing it.
7. No hardcoded email anywhere; `OPENALEX_EMAIL` read via `get_env`.
8. A one-page README section stating the coverage caveats from §3.2 in plain language — an agent using this tool must be able to report the limitation, and it will only do so if the docs say it.
9. PR opened upstream (merge not required).

---

## 10. What this fork does not solve

Citation-graph coverage is bad for older and non-English literature, and this fork cannot fix that — it can only make the badness visible. For the 1972 anchor paper, backward coverage is 6 references in OpenAlex and elided in Semantic Scholar. Any cascade seeded on pre-digital work will be systematically incomplete in a direction that correlates with age, discipline, and publisher.

Treat §6 Test 4 and §9 criterion 8 as the load-bearing responses to this. The tool's job is an honest one hop, with its uncertainty legible to whatever runs the recursion.
