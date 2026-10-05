# Feature design: AppMind application configuration

**Status:** Proposed (nothing here is implemented yet) · **Scope:** a generic, declarative way to onboard any application to AppMind without changing code, in line with the platform vision.

**Files in this folder**

| File | What it is |
|---|---|
| `app-config-design.md` | This document: layers, every config option, format recommendation, principles, open decisions |
| [`appmind-app.schema.json`](appmind-app.schema.json) | The machine-readable schema (JSON Schema 2020-12) for one application's profile |
| [`orderflow.example.yaml`](orderflow.example.yaml) | A worked example: OrderFlow, using the values AppMind hardcodes for it today |

The schema and the example were verified together: the schema is itself valid, the example passes it, 25 deliberate mistakes (typos, out-of-range values, secrets written inline, contradictory settings) are rejected, and valid variations are accepted (a connector-based source, a custom question type, scheduled indexing, and a four-key minimal profile).

---

## 1. Why configuration, and why now

AppMind is meant to become a platform that answers like a subject-matter expert for many teams' applications. Today everything that makes it answer well for **OrderFlow** is baked into code:

| What is hardcoded for OrderFlow | Where |
|---|---|
| The topic the off-topic guardrail compares questions to, and its threshold (0.18) | `TOPIC_DESCRIPTION`, `MIN_TOPIC_SCORE` in `guardrails/input_guardrail.py` |
| The keyword-to-component map and question-type keywords | `supervisor` in `app/graph.py` |
| Which sources each question type searches and how many chunks | `BASE_TOP_K` in `rag/search.py` |
| Which question types use the code graph and source files | `QUESTION_TYPES_USING_AST_TOOLS`, `QUESTION_TYPES_READING_SOURCE_FILES` in `app/retrieval.py` |
| The relevance cutoff, retry widening, file and component caps | `rag/search.py`, `app/retrieval.py`, `mcp_clients/ast_client.py` |
| Confidence thresholds, penalties and the retry cap | `confidence_gate`, `route_after_gate` in `app/graph.py` |
| The PII patterns | `guardrails/input_guardrail.py` |
| The docs and incidents folders | `DOMAIN_FOLDERS` in `ingest/run_ingestion.py` |
| The code repository to index | `indexer/targets.toml` |
| The model names, timeouts and token caps | `app/llm.py`, `rag/search.py` |
| The eval questions and ground truth | `evals/dataset.py` |
| The UI title and example question | `ui/streamlit_app.py` |

Onboarding a second application would mean editing code in a dozen places. The goal is that it means adding one file.

---

## 2. Three layers of configuration

| Layer | Scope | Who edits it | Holds |
|---|---|---|---|
| **Platform** | The whole AppMind deployment | Platform operator | Infrastructure endpoints (Postgres, Qdrant, Redis), secrets, default models, global limits, tenant limits, log format |
| **Application profile** | One onboarded application | That application's team | Everything in section 3 |
| **Repository manifest** (optional) | One repository, kept in the team's own repo | That repository's team | A small self-description (source root, docs paths, language, owners), merged over the matching profile entry |

**Precedence:** built-in defaults, then platform, then application profile, then question-type override. A profile may `extends` a base profile (for example an organization-wide one).

**Secrets never appear in these files.** A profile names the environment variable that holds a secret (`auth: { secret: GITHUB_TOKEN }`), and `secrets.required` lists variables that must be set, checked at startup so a missing one fails fast.

This document and the schema cover the **application profile**. The platform layer stays environment variables and `.env` as today; the repository manifest is a deliberate subset of the profile and gets its own small schema when the indexer's Phase 2 needs it.

---

## 3. The application profile: every option

**Tier:** **R** = required, **O** = optional with a sensible default, **A** = advanced tuning that rarely changes. Only four things are required to onboard an application: `schema_version`, `app` (id and name), `scope.description`, and at least one `sources.code` entry. The right column shows where the setting is hardcoded today.

### 3.1 Identity and ownership

| Key | Tier | Controls | Today |
|---|---|---|---|
| `app.id` | R | Stable machine id; used in storage names and logs | — |
| `app.name` | R | Display name in prompts and the UI | "OrderFlow" in prompts, UI, server name |
| `app.description`, `app.owners`, `app.tags` | O | Description, who to contact, grouping | — |
| `extends` | O | Base profile this one overrides | — |

### 3.2 Scope and vocabulary

| Key | Tier | Controls | Today |
|---|---|---|---|
| `scope.description` | R | Prose about what the app covers; the guardrail embeds it and compares each question to it | `TOPIC_DESCRIPTION` |
| `scope.out_of_scope` | O | Topics explicitly not covered | — |
| `scope.aliases` | O | Business words mapped to components (`PaymentClient: [payment, charge]`) | keyword map in the supervisor |
| `scope.glossary` | O | Domain terms and their meaning, supplied to prompts | — |

### 3.3 Sources

Every source carries the same common fields: `description`, `include`, `exclude`, `auth`, `refresh` (`trigger`: manual, webhook or schedule, plus a cron `schedule`), and `classification` (public, internal, confidential, restricted).

| Key | Tier | Controls | Today |
|---|---|---|---|
| `sources.code[]` | R (at least one) | `repo`, `host`, `ref`, `source_root`, `language`, `manifest` | `indexer/targets.toml` |
| `sources.docs[]` | O | Architecture, requirements, runbooks | `DOMAIN_FOLDERS` |
| `sources.incidents[]` | O | Postmortems or an incident-tracker query | `DOMAIN_FOLDERS` |
| `sources.specs[]` | O | ADRs, design and spec files (for example spec-driven development outputs), OpenAPI | not built |
| `sources.other[]` | O | Tickets, wikis, other connectors | not built |

A non-code source gives its location in exactly one of three ways: a local `path`, a `repo` plus `paths` globs, or a `connector` (`type`, `url`, `query`) for an external system. `kind` (architecture, requirements, runbook, incident, adr, spec, api, ticket, wiki, other) and `format` (markdown, text, html, openapi) describe its content.

### 3.4 Architecture map (for multi-repository applications)

| Key | Tier | Controls | Today |
|---|---|---|---|
| `components[]` | O | A component or service: `id`, `repo`, `owner`, `criticality`, `depends_on` | derived from the code graph only |
| `links[]` | O | Declared connections static analysis cannot see: `from`, `to`, `via` (http, grpc, queue, event, database, file, other) | not possible |

### 3.5 Question types and personas

| Key | Tier | Controls | Today |
|---|---|---|---|
| `question_types.<type>.enabled` | O | Turn a type on or off | three hardcoded types |
| `question_types.<type>.sources` | O | Source groups the type draws on | `BASE_TOP_K` |
| `question_types.<type>.top_k` | O | Chunks per source group | `BASE_TOP_K` |
| `question_types.<type>.use_code_graph` | O | Look up dependents and callers | `QUESTION_TYPES_USING_AST_TOOLS` |
| `question_types.<type>.attach_source_files` | O | Also attach the real source text of resolved components (requires `use_code_graph`) | `QUESTION_TYPES_READING_SOURCE_FILES` |
| `question_types.<type>.classifier` | O | `mode` (keywords or llm), `keywords`, `prompt` | keyword stub in the supervisor |
| `question_types.<type>.personas` | O | Personas this type serves | not built |
| `personas[]` | O | `id`, `name`, `description`, `source_weights` (how much each source group matters for this audience), `answer_style`, `default` | not built |

Custom question types are allowed (the built-in names are `business_functional`, `incident_rca`, `impact_analysis`).

### 3.6 Retrieval tuning (advanced)

| Key | Tier | Default | Today |
|---|---|---|---|
| `retrieval.min_score` | A | 0.25 | `MIN_SCORE` |
| `retrieval.retry_extra_top_k` | A | 3 | `RETRY_EXTRA_TOP_K` |
| `retrieval.max_source_files` | A | 3 | `MAX_SOURCE_FILES` |
| `retrieval.max_components` | A | 3 | `MAX_COMPONENTS` |
| `retrieval.min_component_name_length` | A | 6 | `MIN_NAME_LENGTH` |

The defaults are measured values for the reference application. `min_score` and the topic threshold must be re-measured when a corpus or embedding model changes.

### 3.7 Quality and escalation

| Key | Tier | Default | Today |
|---|---|---|---|
| `quality.escalate_below` | O | 0.5 | `route_after_gate` |
| `quality.flag_penalty` | A | 0.3 | `confidence_gate` |
| `quality.error_cap` | A | 0.4 (keep below `escalate_below`) | `confidence_gate` |
| `quality.max_retries` | O | 2 | `retry_count < 2` |
| `quality.critic.enabled`, `strictness` | O | true, standard | the `pipeline_mode` enum |
| `quality.grounding.fuzzy_min` | A | — | `FUZZY_GROUNDED_MIN` |
| `escalation.contacts`, `channel`, `message` | O | generic message | hardcoded text |

### 3.8 Guardrails

| Key | Tier | Today |
|---|---|---|
| `guardrails.pii.enabled`, `builtin` (email, phone, ssn), `custom` (`name` + `regex`), `action` (block or redact) | O | three regexes |
| `guardrails.topic.enabled`, `threshold` | O | `MIN_TOPIC_SCORE` = 0.18 |
| `guardrails.blocked_topics` | O | — |
| `guardrails.output.require_citations` | O | hardcoded rule |

### 3.9 Models and cost

| Key | Tier | Today |
|---|---|---|
| `models.llm`, and per-role `models.roles` (evidence, critic, synthesis, judge) | O | one model via `APPMIND_LLM_MODEL` |
| `models.embedding` (changing it requires re-indexing every source) | A | `text-embedding-3-small` in two places |
| `models.timeout_s`, `max_output_tokens` | A | `LLM_TIMEOUT_S`, 3000 |
| `budget.max_tokens_per_question`, `max_llm_calls_per_question` | O | — |

### 3.10 Indexing and refresh

| Key | Tier | Today |
|---|---|---|
| `indexing.trigger` (manual, webhook, schedule) and `schedule` (required when scheduled) | O | CLI only |
| `indexing.retention` | A | `APPMIND_INDEXER_KEEP` = 5 |
| `indexing.max_file_bytes`, `languages` | A | `MAX_FILE_BYTES` |
| `indexing.freshness.warn_after` | O | — |

### 3.11 Storage and isolation

| Key | Tier | Today |
|---|---|---|
| `storage.namespace`: a prefix for this app's collections and tables, so one app's data never mixes with another's | O (R in a multi-app deployment) | global names (`docs`, `incidents`) |
| `storage.cache_ttl` | A | `CACHE_TTL_SECONDS` = 24h |
| `storage.audit_retention`, `store_questions` | O | kept forever |

### 3.12 Access and security

| Key | Tier | Controls | Today |
|---|---|---|---|
| `access.allowed_groups` | O | Who may ask about this app | none |
| `access.repo_acl_mapping` | O | Enforce each repository's own access rules on derived answers | none |
| `access.data_classification`, `access.audit` | O | Sensitivity and audit | none |

### 3.13 Evaluation, observability, UI, secrets

| Key | Tier | Today |
|---|---|---|
| `eval.dataset`, `trials`, `metrics`, `pin_snapshot`, `thresholds` | O | `evals/dataset.py` (OrderFlow only), `--trials`, `APPMIND_EVAL_SNAPSHOT` |
| `observability.log_level`, `trace` | O | prints always on |
| `ui.title`, `example_questions`, `locale` | O | hardcoded in `ui/streamlit_app.py` |
| `secrets.required` | O | — |

### 3.14 Platform-level (not per app)

Postgres, Qdrant and Redis endpoints, default models, global timeouts, cache backend, log format, and tenant limits. These stay environment-driven.

---

## 4. Format: JSON vs YAML vs TOML

| | JSON | YAML | TOML |
|---|---|---|---|
| Comments | No: a dealbreaker for hand-written config | Yes | Yes |
| Deep nesting and lists of objects | Noisy | Best | Verbose past about two levels (`[[a.b.c]]`) |
| Multi-line prose (scope description) | Awful (`\n` escapes) | Good (`>` and `\|`) | Good |
| Python support | stdlib | PyYAML (a new declared dependency) | stdlib, read-only (`tomllib`, 3.11+) |
| Pitfalls | None | Indentation; YAML 1.1 turns `no`/`off` into false and `1.10` into a float | Few |
| Ecosystem | Machine to machine | Dominant for configuration (Kubernetes, CI, OpenAPI) | Smaller |

**Recommendation: YAML for the application profile.** Many different teams will write it by hand, and it is nested, list-heavy, and needs comments and multi-line prose. Its pitfalls are managed, not ignored:

- Load with `yaml.safe_load` only.
- Validate with a **Pydantic model** (already in the stack) that rejects unknown keys, so a typo is an error instead of being silently ignored. The JSON Schema is exported from, or kept in sync with, that model and also drives editor autocomplete and inline errors (the `# yaml-language-server: $schema=` line in the example).
- Quote ambiguous values.

**JSON only for machine-to-machine data** (the indexer's graph snapshot is JSON). **TOML** is the right call only if zero dependencies matters more than readability. The indexer's flat `targets.toml` can stay TOML for now, but long-term one format for everything teams author is easier to learn. PyYAML is installed transitively today but not declared, so adopting YAML means adding it to `requirements.txt`.

---

## 5. Validation

Two layers, because JSON Schema cannot express everything:

1. **Structural (this schema):** types, ranges, required keys, unknown keys rejected, secrets as environment-variable names only, and the cross-field rules it *can* express (a keyword classifier needs keywords; `attach_source_files` needs `use_code_graph`; scheduled indexing needs a schedule; a document source has exactly one location).
2. **Semantic (the validator in code, to be built):** ids are unique, exactly one persona is the default, every `components[].repo` appears in `sources.code`, every `depends_on` and `links` endpoint exists, every `scope.aliases` target exists in the code graph, `quality.error_cap` is below `escalate_below`, regexes compile, every variable in `secrets.required` is set, and `question_types` reference real source groups the profile defines.

One limit worth stating: the schema requires `auth.secret` to look like an environment-variable name (uppercase, digits, underscores), which rejects typical tokens pasted inline, but it cannot prove a value is not a secret. A secret scan in CI is the complement.

The schema and example must stay in lockstep: validating `orderflow.example.yaml` against `appmind-app.schema.json` is a check to run in CI.

---

## 6. Design principles

- **Convention over configuration:** four required keys; everything else defaults.
- **Schema as code:** one model is the source of truth for validation, documentation and editor support.
- **Strict:** unknown keys are errors, and the file carries `schema_version` so the schema can evolve.
- **Config is data, behavior stays in code:** a profile selects and tunes behavior; it does not script it.
- **Validate at onboarding**, with clear messages, not at question time.
- **Layered, never duplicated:** defaults, then platform, then application, then question type.

---

## 7. Decisions to confirm

1. **Where profiles live:** in AppMind (`config/apps/<id>.yaml`), in each application's own repository, or a database later. Recommended: start in AppMind, move to a team-owned in-repo manifest.
2. **Format:** accept YAML, with the new dependency and the Pydantic validation.
3. **Manifest format:** the code-index design (`features/code-index-design.md`) and `indexer/targets.toml` currently assume TOML for the registry and the in-repo manifest. If YAML is adopted, decide whether those move with it. The schema's default manifest name is `appmind.yaml`.
4. **Data isolation:** per-application collection and table namespaces (`storage.namespace`), and what happens to today's global `docs`/`incidents` names.
5. **Reload:** whether a profile change needs a restart or is picked up live.
6. **Ownership:** who may edit a profile, and whether a profile change is reviewed like code.
7. **Next step:** an implementation plan (the Pydantic model, a loader with the layering, replacing each hardcoded value in section 1 one at a time with OrderFlow's profile reproducing today's behavior exactly), written like the code-index plan.
