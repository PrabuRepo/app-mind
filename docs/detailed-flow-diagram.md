# AppMind — Detailed Flow Diagram

Node-by-node view of the LangGraph pipeline: exact routing, the `pipeline_mode` fork, the Critic retry loop, and how code evidence reaches the retriever from the code index. For the simplified component-category view, see [`detailed-design.md` §3](detailed-design.md#3-system-design--architecture).

### Component diagram

```mermaid
flowchart TB
    subgraph entry["Entry points"]
        UI["Streamlit UI"]
        EVALH["Eval harness (evals/run_eval.py)"]
    end

    subgraph pipeline["LangGraph pipeline (app/graph.py) - pipeline_mode selects baseline / critic_off / critic_on"]
        direction TB
        IG["input_guardrail"] --> SUP["supervisor"] --> RES["research"] --> RET["retriever"] --> EV["evidence agent (LLM)"] --> CR["critic agent (LLM)"] --> GATE["confidence_gate"]
        GATE --> ESC["escalate"]
        GATE --> SYN["synthesis (LLM)"]
        CR -.->|"retry, capped at 2"| RES
        ESC --> OG["output_guardrail"]
        SYN --> OG
        OG --> MW["memory_write"]
    end

    subgraph knowledge["Knowledge and tools (read at question time)"]
        QDRANT[("Qdrant - docs + incidents")]
        CTX["code_context (read-only client)"]
        AST["Custom AST MCP server<br/>(loads a code snapshot)"]
    end

    subgraph storage["Storage"]
        PG[("PostgreSQL - audit trail<br/>+ code index: snapshots, files, heads")]
        REDIS[("Redis - investigation cache")]
    end

    subgraph indexing["Indexing (offline, separate project: indexer/)"]
        GH["Target repositories (GitHub)"]
        IDX["indexer<br/>pinned commit, graph + source files"]
    end

    subgraph offlineeval["Evaluation (offline, not live traffic)"]
        JUDGE["LLM-as-Judge"]
        ASTCHECK["Deterministic graph check (Impact Analysis ground truth)"]
    end

    UI -->|"cache-checked"| REDIS
    UI --> IG
    EVALH -->|"27 runs, bypasses cache"| IG
    EVALH --> JUDGE
    EVALH --> ASTCHECK

    RET --> QDRANT
    RET --> CTX
    RET --> AST
    CTX --> PG
    CTX -.->|"exports the snapshot to a file"| AST
    ASTCHECK -.->|"pinned snapshot"| CTX

    GH --> IDX
    IDX -->|"one transaction per repo"| PG

    MW --> PG
    MW --> REDIS
```

*Solid arrows are direct calls; dotted arrows are the retry loop and the snapshot hand-off to the AST server. Answering a question never contacts GitHub: the indexer (offline, run on demand or on a schedule) reads each repository once at a pinned commit and stores the result, and the retriever reads only that store. The Indexing and Evaluation subgraphs are offline tooling, never part of a live request; evaluation invokes the pipeline the same way the UI does.*
