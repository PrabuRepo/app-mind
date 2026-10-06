# Feature design: AppMind application configuration

**Status:** Implemented (`app_profile/`, `config/apps/orderflow.yaml`; ingestion, the topic guardrail, the supervisor and the indexer hand-off all read the profile) · **Scope:** a small, declarative profile that onboards any application to AppMind without code changes, in line with the platform vision.

**Files in this folder**

| File | What it is |
|---|---|
| `app-config-design.md` | This document |
| [`app_profile/appmind-app.schema.json`](../../app_profile/appmind-app.schema.json) | The schema (JSON Schema 2020-12) for one application's profile |
| [`orderflow.example.yaml`](orderflow.example.yaml) | OrderFlow written as a profile, annotated. The live profile is [`config/apps/orderflow.yaml`](../../config/apps/orderflow.yaml) |
| [`app_profile/`](../../app_profile/) | The implementation: loader, semantic checks, registry, indexer export, and tests |

The schema is verified by `python -m app_profile.test_app_profile` (62 checks): the schema is itself valid; the example, the smallest possible profile, and the core snippet proposed during review all validate; and deliberate mistakes (typos, secrets written inline, escaping source roots, contradictory document locations, unimplemented keys) are rejected through the real loader. `python -m app_profile.check` validates every profile in `config/apps/` plus the example.

---

## 1. The idea in one paragraph

An application is onboarded by adding **one small file**: who it is, and where its knowledge lives (code repositories, docs, incident reports). Everything else (retrieval limits, confidence thresholds, guardrail patterns, models) keeps a sensible default in code and is **not** configurable until a real second application proves it must differ. The schema holds only options AppMind actually honors.

The smallest valid profile is five lines:

```yaml
schema_version: 1
app: { id: billing, name: Billing }
sources:
  code: [{ repo: acme/billing }]
```

---

## 2. Why this is needed

Before this change, onboarding a second application would have meant editing code in a dozen places, because everything that made AppMind answer well for **OrderFlow** was hardcoded. Each item below has a disposition: it becomes **core config**, is **fixed in code** (made generic, not exposed), or is **reserved** (a default stays in code; the option is documented in Appendix A for when it's needed).

| Hardcoded for OrderFlow before | Where it was | Disposition |
|---|---|---|
| The code repository to index | `indexer/targets.toml` | **Core config:** `sources.code` |
| The docs and incidents folders | `DOMAIN_FOLDERS` in `ingest/run_ingestion.py` | **Core config:** `sources.docs`, `sources.incidents` |
| The topic the off-topic guardrail compares questions to | `TOPIC_DESCRIPTION` in `guardrails/input_guardrail.py` | **Core config (optional):** `scope.description`. The threshold (0.18) stays a code default |
| Which component a question means when it never names one | `supervisor` in `app/graph.py` | **Core config (optional):** `scope.aliases`. Measured: no generic method (names in retrieved text, embeddings, token overlap) finds it, because "charged twice means PaymentClient" is domain knowledge. Question-type keywords stay fixed in code |
| Sources and top-k per question type | `BASE_TOP_K` in `rag/search.py` | Reserved (`question_types`) |
| Which question types use the code graph and source files | `app/retrieval.py` | Reserved |
| Relevance cutoff, retry widening, file and component caps | `rag/search.py`, `app/retrieval.py`, `mcp_clients/ast_client.py` | Reserved (`retrieval`) |
| Confidence thresholds, penalties, retry cap | `confidence_gate`, `route_after_gate` in `app/graph.py` | Reserved (`quality`) |
| The PII patterns | `guardrails/input_guardrail.py` | Reserved (`guardrails`) |
| Model names, timeouts, token caps | `app/llm.py`, `rag/search.py` | Platform environment; reserved per app (`models`) |
| Eval questions and ground truth | `evals/dataset.py` | Reserved (`eval`); needed per app only when evaluating it |
| UI title and example question | `ui/streamlit_app.py` | Derived from `app.name`; reserved (`ui`) |

---

## 3. Layers

| Layer | Scope | Who edits it | Holds |
|---|---|---|---|
| **Platform** | The whole AppMind deployment | Platform operator | Infrastructure endpoints (Postgres, Qdrant, Redis), secrets, default models, global limits. Stays environment variables and `.env` |
| **Application profile** | One onboarded application | That application's team | This document's schema |
| **Repository manifest** (later) | One repository, kept in the team's own repo | That repository's team | A small self-description merged over the matching `sources.code` entry. Not in the schema yet; it arrives with the indexer's multi-repo phase |

Precedence is built-in defaults, then platform, then the application profile.

**Secrets never appear in a profile.** A source names the environment variable that holds its token (`auth: { secret: GITHUB_TOKEN }`); when omitted, the platform's `GITHUB_TOKEN` is used.

---

## 4. The profile schema

Required: `schema_version`, `app.id`, `app.name`, and at least one `sources.code[].repo`. Everything else is optional.

| Key | Required | Default | Meaning | Replaces today |
|---|---|---|---|---|
| `schema_version` | yes | — | Always `1`; bumps only for a breaking change | — |
| `app.id` | yes | — | Stable machine id (`^[a-z][a-z0-9-]{1,40}$`), used in logs and storage names | — |
| `app.name` | yes | — | Display name, used in prompts and the UI | "OrderFlow" in prompts and UI |
| `app.description` | no | — | Free text | — |
| `app.owners` | no | — | Teams or people to contact; unique | — |
| `scope.description` | no | skip the topic guardrail | Prose about the app's domain, at least 40 characters; each question is compared to it | `TOPIC_DESCRIPTION` |
| `scope.aliases` | no | none | A component name mapped to words that mean it (`PaymentClient: [payment, charge]`). Used for incident and impact questions that do not name a component. A word matches as part of a word; the first listed component wins | the supervisor's keyword hints |
| `sources.code[].repo` | yes (one or more) | — | `owner/name` | `indexer/targets.toml` |
| `sources.code[].ref` | no | `main` | Branch or tag; resolved to an immutable commit SHA when indexed | same |
| `sources.code[].source_root` | no | `.` | Directory inside the repo holding the code (for example `src`); relative and inside the repo | same |
| `sources.code[].exclude` | no | none | Globs to skip (for example `**/tests/**`); `.venv`, `node_modules` and similar are always skipped | same |
| `sources.code[].auth` | no | platform `GITHUB_TOKEN` | `{ secret: ENV_VAR_NAME }` | environment |
| `sources.docs[]`, `sources.incidents[]` | no | none | Documentation and incident reports; kept separate because incident questions weight them differently | `DOMAIN_FOLDERS` |

A docs or incidents entry gives its location in **exactly one** of two ways:
- `path`: a local file or folder.
- `repo` + `paths`: path globs inside a repository (optionally `ref` and `auth`). This is what lets other teams' docs stay in their own repositories instead of being copied into AppMind.

### What happens when optional parts are missing

| Missing | Behavior |
|---|---|
| `scope.aliases` | No component hint: a question that never names a component gets no code evidence, but is still answered from docs and incidents |
| `scope` | The topic guardrail is skipped. An off-topic question is still caught later, when retrieval finds nothing relevant and confidence drops to zero. Correct, just a little later and less efficient |
| `docs` / `incidents` | Questions are answered from code evidence only, so most business and incident questions will escalate honestly |
| `auth` | The platform's `GITHUB_TOKEN` is used |
| `app.description` | Prompts name only the app ("OrderFlow"), without the short phrase after it |
| `app.owners` | Nobody is named in escalations (the generic message is used) |

Known loophole: `scope: {}` is valid and does nothing, because `description` is optional inside `scope`. It can be tightened to "required when `scope` is present" if preferred.

---

## 5. Strict by design

- **Unknown keys are errors**, so a typo like `exclud:` is caught instead of ignored.
- **A key is in the schema only if AppMind honors it.** Accepting a setting that silently does nothing is worse than rejecting it, so every reserved option in Appendix A is rejected today (tested). Promoting one means: a real application needs it, the code honors it, the schema and a test are updated, and its default reproduces current behavior exactly.
- **Compatibility:** a profile that uses a key a newer AppMind added fails on an older one with a clear message, which is the intended behavior.
- **Secrets are references:** `auth.secret` must look like an environment-variable name (uppercase, digits, underscores), which rejects tokens pasted inline. It cannot prove a value isn't a secret, so a secret scan in CI is the complement.

---

## 6. Format: JSON vs YAML vs TOML

| | JSON | YAML | TOML |
|---|---|---|---|
| Comments | No: a dealbreaker for hand-written config | Yes | Yes |
| Nesting and lists of objects | Noisy | Best | Verbose past about two levels |
| Multi-line prose (scope description) | Awful (`\n` escapes) | Good | Good |
| Python support | stdlib | PyYAML (a new declared dependency) | stdlib, read-only (`tomllib`, 3.11+) |
| Pitfalls | None | Indentation; YAML 1.1 turns `no`/`off` into false and `1.10` into a float | Few |
| Ecosystem | Machine to machine | Dominant for configuration | Smaller |

**Decision: YAML for the application profile.** Teams will write it by hand, and it needs comments, lists of objects and multi-line prose. Manage its pitfalls: load with `yaml.safe_load` only, validate against a model that rejects unknown keys, and quote ambiguous values. The profile is small, so TOML would also work if avoiding a dependency matters more than familiarity; JSON stays for machine-to-machine data (the indexer's graph snapshot). PyYAML is installed transitively today but not declared, so adopting YAML means adding it to `requirements.txt`.

---

## 7. Validation

Two layers, because JSON Schema cannot express everything:

1. **Structural (the schema file):** types, patterns, required keys, unknown keys rejected, secrets as environment-variable names only, and "exactly one location" for document sources.
2. **Semantic (`app_profile/semantic.py`):** `app.id` is unique across profiles and matches the file name; every `auth.secret` variable is set; every local `docs`/`incidents` `path` exists. Not built yet: that each `repo` is reachable with its token, that `source_root` exists in it, that each `scope.aliases` component exists in the code graph, and that `scope.description` is not a copy of another app's. Each needs the network or the database, so they are opt-in additions.

`python -m app_profile.check` validates the example against the schema along with every real profile and exits non-zero on failure, so the two cannot drift. The repository has no CI configuration yet; wire that command in when it does.

---

## 8. Decisions

1. **Where profiles live: decided.** `config/apps/<id>.yaml` inside AppMind, where `<id>` is the profile's `app.id` (for example `orderflow` gives `config/apps/orderflow.yaml`). The loader checks that the filename matches `app.id`. `APPMIND_APP` selects the profile; with a single file it is picked automatically. Moving to a file inside each application's own repo later only changes the loader's search path.
2. **Format: decided, YAML.** Loaded with `yaml.safe_load`, validated strictly, and PyYAML declared in `requirements.txt` (§9, step 1).
3. **How this meets the indexer: decided, keep as is.** `sources.code[]` carries the same fields as `indexer/targets.toml` (`repo`, `ref`, `source_root`, `exclude`). The indexer is a self-contained project that must not import AppMind, so a build-time step exports a registry file from the profile, and the indexer stays TOML and unchanged. Whether the code-index design's own in-repo manifest follows this format is left to that design.
4. **Data isolation: deferred, with a trigger.** Keep the global `docs` and `incidents` collections while there is one application. Before a second application is onboarded, migrate to per-application collections (`<app.id>_docs`, `<app.id>_incidents`), and add `app.id` to the Redis cache key and the audit-trail row. Separate collections are preferred over an `app_id` tag plus a search filter, because a missed filter would leak one application's data into another's answers, while separate collections cannot. Until then, nothing in the loader or the profile depends on the collection names.
5. **`scope: {}`: decided, allowed.** It is treated the same as omitting `scope`: the topic guardrail is skipped and the loader logs that.
6. **Ownership: a convention, nothing to build.** A profile is a file in git and changes by pull request. Add a `CODEOWNERS` entry keyed on `app.owners` when other teams start adding profiles.
7. **Next step:** the implementation plan in §9.

---

## 9. Implementation plan

**Rule for every step:** OrderFlow's profile must reproduce today's behavior exactly. Each step ends with a test proving it, and the existing suites (`app/`, `rag/`, `guardrails/`, `indexer/`, `code_context/`) keep passing. Steps are ordered so each one ships and can be reverted on its own.

### Where the hardcoded values live today

| Value | Today | Replaced by |
|---|---|---|
| Code repo, ref, source_root, exclude | `indexer/targets.toml` (now generated) | `sources.code[]` |
| Docs and incidents folders | `DOMAIN_FOLDERS` in `ingest/run_ingestion.py` (removed in step 3) | `sources.docs[]`, `sources.incidents[]` |
| Topic text for the off-topic guardrail | `TOPIC_DESCRIPTION` in `guardrails/input_guardrail.py` (removed in step 4) | `scope.description` |
| Target repo for questions | `APPMIND_CODE_REPO` env var (`code_context/snapshots.py`) | `sources.code[0].repo`, env var as override |
| The application's name in the Evidence, Critic, Synthesis, baseline and judge prompts, and the UI intro | the prompt constants in `agents/` and `llm_as_judge/`, `ui/streamlit_app.py` (removed after step 7) | `app.name` and `app.description`, filled in by `app/prompts.py` |
| Component hint in the supervisor | OrderFlow keywords/names in `app/graph.py` (removed in step 6) | `scope.aliases` |
| Topic threshold, top-k, retry and escalation limits | constants in code | **stay in code** (Appendix A) |

### Steps

1. **Loader and validator: `app_profile/` package, nothing consuming it yet. Implemented.**
   - `loader.py`: read one YAML file with `yaml.safe_load`, validate against `appmind-app.schema.json` (`jsonschema`), return a frozen Pydantic model (`AppProfile`, `CodeSource`, `DocumentSource`) with the schema defaults applied (`ref: main`, `source_root: .`, `auth: GITHUB_TOKEN`). Errors name the file and the key path.
   - `semantic.py`: the checks in §7 (unique `app.id`, secret env var set, `source_root` and local `path` exist). Repository reachability is an opt-in check, so offline tests and CI do not need a token.
   - The schema lives in `app_profile/appmind-app.schema.json`, the single source of truth. This folder keeps the design doc and the example only.
   - Declare `pyyaml` and `jsonschema` in `requirements.txt`.
   - Tests (plain runnable module, `check()` helpers): port the 40 checks from the scratch validation script, add loader error-message and default-application checks, and run `orderflow.example.yaml` through the loader.
   - **Done when:** the OrderFlow example loads into a model and every §5 rule is enforced by a test.

2. **Create the real profile: `config/apps/orderflow.yaml`. Implemented.**
   - Copy the example. Add a test that fails if its `scope.description` differs from today's `TOPIC_DESCRIPTION`, and that its code and folder entries equal today's `targets.toml` and `DOMAIN_FOLDERS` values. These equality tests are the safety net for steps 3 to 5 and are deleted with the old constants.
   - Selection: `APPMIND_APP` env var names the profile id; default to the only profile present, error if several (the same rule as `target_repo()`).
   - `app_profile/registry.py` holds `load_all()` and `select_profile()`. `python -m app_profile.check` validates every file under `config/apps/` plus the design example, and exits non-zero on failure; an unset secret is only a warning unless `--strict`.
   - **Done when:** the check passes, the equality tests pass, and altering any value in the profile fails them. Run the check in CI once CI exists.

3. **Ingestion reads the profile. Implemented.**
   - `ingest/run_ingestion.py` builds its domain-to-folder map from `sources.docs` and `sources.incidents` instead of `DOMAIN_FOLDERS`. A folder with several `path` entries is ingested as one collection.
   - Entries that use `repo` + `paths` are rejected with a clear "not supported yet" error until a real application needs them (the schema allows them, the loader honors only what ingestion implements; see the open item below).
   - Collection names stay `docs` and `incidents` (decision 4 default).
   - `python -m ingest.run_ingestion --dry-run` chunks without calling OpenAI or Qdrant and prints the count per collection. `DOMAIN_FOLDERS` is deleted, together with its equality checks in `app_profile/test_orderflow_profile.py`.
   - **Done when:** a dry run produces the same chunk counts per collection as before, checked against the current Qdrant contents. Verified: docs 13 and incidents 17, and every chunk's text, source and heading equals the stored point, in the same order. The same dry run works inside the Docker image.

4. **Guardrail reads the profile. Implemented.**
   - `guardrails/input_guardrail.py` takes the reference text from `scope.description`; when absent the topic check is skipped and logs that it was. `MIN_TOPIC_SCORE` stays a constant.
   - **Done when:** the existing guardrail tests pass unchanged, the same on-topic and off-topic questions score the same, and a profile without `scope` lets an off-topic question through the guardrail. Verified: the profile's text equals the removed constant (checked against `HEAD`); live, the 9 dataset questions score 0.28 to 0.61 and 7 off-topic questions score -0.02 to 0.13, none of the 9 blocked and all 7 blocked, as before. `guardrails/test_input_guardrail_profile.py` covers the wiring offline. A broken profile raises instead of failing open; an embedding failure still fails open.

5. **Indexer and code context read the profile. Implemented.**
   - The indexer must not import AppMind. The hand-off is a build-time step: `python -m app_profile.export_targets` writes the `[[target]]` list the indexer already understands (`targets.toml` format) from the profile, and the indexer container reads that generated file. The indexer's code, its TOML registry and its boundary test do not change.
   - `code_context.snapshots.target_repo()` falls back to the profile's first code repo when `APPMIND_CODE_REPO` is unset.
   - The committed `indexer/targets.toml` is renamed `indexer/targets.example.toml`, so the indexer still ships a registry example when it moves to its own repository (the boundary test's required-file list changed from `targets.toml` to `targets.example.toml`; that is the one boundary-test edit). `indexer/targets.toml` is now generated and git-ignored; `export_targets` writes it by default, which is the file the indexer reads with no arguments.
   - An `auth.secret` other than `GITHUB_TOKEN` is refused at export time, because the indexer reads one platform token and would ignore it.
   - Docker: a one-shot `export-targets` service (the app image, which holds the loader) writes the registry into a shared `appmind_generated` volume; the `indexer` service waits for it to succeed, mounts the volume read-only and runs with `--targets /generated/targets.toml`. Every `docker compose run --rm indexer` therefore regenerates it first.
   - **Done when:** the generated file equals today's `targets.toml` in content, the indexer's own code and tests are unchanged and `code_context/test_boundaries.py` passes, and a snapshot indexed from the generated file is identical to the current one. Verified: the exported targets equal `HEAD`'s `targets.toml` as parsed data; `docker compose run --rm indexer` ran export-targets, then the indexer read the generated file and confirmed commit `244ea40` as already indexed, leaving the same snapshot head and snapshot count (1).

6. **Component hints in the supervisor come from the profile. Implemented, as `scope.aliases`.**
   - `app/graph.py` no longer names any application component. The supervisor asks `app/component_hints.py`, which matches the question against `scope.aliases` from the profile (case-insensitive, a word matches as part of a word, first listed component wins). It is only a fallback: `mcp_clients/ast_client.py` matches component names written in the question against the code graph first.
   - Only incident and impact questions get a hint; business questions never do, as before. Question-type keywords (`affect`, `depend`, `break`, `incident`, `charge`, `bug`) stay in code; the supervisor is still a keyword stub, and replacing it with a classifier is separate work.
   - `config/apps/orderflow.yaml` carries `PaymentClient: [payment, charge]` and `InventoryClient: [invent, stock, oversell]`, which reproduce the removed hints.
   - **Why a config key and not detection from the graph.** Measured before changing code: the supervisor's hints are only a fallback, and 7 of the 9 dataset questions resolve without it. Two rely on it, both resolving to `PaymentClient`: "Why were customers charged twice ... (INC-1001)" and "Can the payment retry logic ever cause a duplicate charge ...". Three generic alternatives were tried on the real snapshot and chunks, and none reproduced `PaymentClient`:
     - *Component names mentioned in the retrieved docs and incidents:* the INC-1001 text never names a component.
     - *Embedding similarity to component descriptions:* the INC-1001 question ranks `OrderPlacementError` first and `PaymentClient` is not in the top three.
     - *Token overlap between component names and the question plus incident text:* a three-way tie on `Order*` classes.
     The link from "charged twice" to `PaymentClient` is domain knowledge that neither the names nor the retrieved text carry, so this is the case Appendix A reserved `scope.aliases` for.
   - **Done when:** the same 9 questions resolve to the same components, code chunks and errors as before. Verified by running `retrieve()` for all 9 before and after: resolved component, code chunks and errors are identical for every question. The one difference is the supervisor's own guess for the two impact questions, which used to default to `OrderService` and now comes from their wording (`PaymentClient`, `InventoryClient`); the AST client had already resolved both from the component named in the question, so nothing downstream changed. The old `OrderService` default for an impact question that names no component is deliberately not reproduced: it was an OrderFlow-specific guess. `app/test_component_hints.py` pins the old behavior for all 9 questions and checks that the supervisor's code names no OrderFlow component.
   - **Limits.** An alias that names a component the code graph does not contain fails at lookup time as a retrieval error, not at load time (checking it needs the database; add it to the semantic validator when the indexer hand-off is automated).

7. **Documentation and cleanup. Implemented.**
   - Follow-up found after step 7: the agent prompts and the UI intro still named OrderFlow, a gap the original list of hardcoded values missed. Fixed: the prompts hold `{app_name}` / `{app_label}` placeholders, `structured_call` fills them from the profile (`app/prompts.py`), and the UI reads `app.name`. `{app_label}` is `app.name` followed by `app.description` when set, so OrderFlow's profile carries `description: an order-processing service`. Verified: all five rendered prompts (Evidence, Critic, Synthesis, baseline, judge) are byte-identical to the previously hardcoded text, so no LLM behavior changes; `app/test_prompts.py` renders them for a second made-up application and checks nothing of OrderFlow remains.
   - Update `README.md` (setup now starts with the profile), `CLAUDE.md`, `docs/detailed-design.md`, and the indexer docs that mention `targets.toml`. Update `features/code-index-design.md` where it assumes a TOML registry.
   - Status in this file's header changes from "Proposed" to implemented, and the example file's "not yet read by the code" note is removed.

### Acceptance for the whole change

- Onboarding a second application means adding one file under `config/apps/` and its repositories: no Python edits, apart from decision 4's open item below.
- With the OrderFlow profile, behavior is identical to today: same chunk counts, same guardrail decisions, same snapshot, same eval results for the Impact Analysis questions.
- A typo, a missing required key or a reserved option fails at startup with the file name and key path, before any LLM or database cost.
- No secret value appears in a profile, a log or the generated indexer file; only environment-variable names.

### Risks and rollback

| Risk | Mitigation |
|---|---|
| Profile and schema drift | One schema file, loaded by the code and by CI |
| YAML surprises (`no` becomes false) | `safe_load` only, schema types reject a boolean where a string is required, quote ambiguous values in the example |
| Generated indexer file gets hand-edited | Header comment, git-ignored, regenerated on every indexer run |
| Step 6 changes answers | It is last, measured against the dataset, and reverts alone |
| Schema allows a source the code does not implement (`repo` + `paths` docs) | Loader rejects it explicitly, or ingestion implements it before step 3 completes; never a silent no-op |

Each step is one commit. Rolling one back restores the previous constant, because the constants are deleted only after their equality test has passed in that same step.

### How the decisions in §8 apply to this plan

| Decision | What the plan does | Cost of changing later |
|---|---|---|
| 1. Where profiles live | `config/apps/<id>.yaml` in AppMind | Low: only the loader's search path changes |
| 3. Indexer hand-off | Export a generated registry; the indexer stays TOML and untouched | Low: the export step is replaceable |
| 4. Data isolation | Keep global `docs` / `incidents` collections for the single app; migrate before a second app is onboarded | Medium: per-app collection names, a re-ingest, and `app.id` in the cache key and audit row |
| 5. `scope: {}` | Allowed (equivalent to omitting `scope`); the loader logs that the topic guardrail is off | Trivial: add `minProperties: 1` to the schema |
| 6. Ownership | Pull-request convention only | None |

---

## Appendix A. Reserved options

These were considered and deliberately **not** put in the schema, because no application needs them yet and the code does not honor them. Each lists the situation that would justify adding it. Today the value is a default in code.

| Option group | Would control | Add when |
|---|---|---|
| `scope.glossary`, `out_of_scope` | Domain terms, excluded topics | Questions use vocabulary the guardrail and retrieval cannot place. (`scope.aliases` was promoted out of this row in step 6.) |
| `question_types` | Per type: `enabled`, source groups, `top_k`, `use_code_graph`, `attach_source_files`, `classifier` (keywords or llm), personas. Custom types allowed | An app needs different sources or a custom question type |
| `personas` | Product, developer or operations perspectives: source weights, answer style, default | Persona-aware answering is built |
| `retrieval` | `min_score` (0.25), `retry_extra_top_k` (3), `max_source_files` (3), `max_components` (3), `min_component_name_length` (6) | A second app's corpus needs different measured values |
| `quality`, `escalation` | `escalate_below` (0.5), `flag_penalty` (0.3), `error_cap` (0.4), `max_retries` (2), critic on/off and strictness, grounding threshold; escalation contacts, channel, message | A team needs a different escalation bar or wants to route escalations |
| `guardrails` | PII built-ins and custom regexes, block or redact, topic threshold (0.18), blocked topics, require citations | Another app has different sensitive patterns or topic breadth |
| `models`, `budget` | Default model, per-role overrides (evidence, critic, synthesis, judge), embedding model, timeouts, token caps, per-question budget | Cost or quality needs differ per app. Changing the embedding model requires re-indexing |
| `indexing` | Trigger (manual, webhook, schedule), cron, snapshot retention (5), max file bytes (200000), languages, freshness warning | Automation arrives (indexer phase 3) |
| `storage` | Namespace, cache TTL (24h), audit retention, whether to store question text | More than one app shares a deployment |
| `access` | Allowed groups, repository access mapping, data classification, audit | Several teams share an instance or an app is sensitive |
| `components`, `links` | An architecture map and declared connections (HTTP, queue, event) that static analysis cannot see | Multi-repository applications need cross-service impact analysis |
| Source extras | `connector` (issue trackers, wikis), per-source `include`, `refresh`, `classification`, `kind`, `format` | A source is not a repo or folder, or needs its own refresh or sensitivity |
| `eval` | Dataset path, trials, metrics, pinned snapshot, thresholds | Evaluating a second app |
| `ui`, `observability`, `secrets.required`, `extends` | Title and example questions, log level and tracing, startup check for required environment variables, a base profile to inherit from | Each is a small convenience; add on demand |
