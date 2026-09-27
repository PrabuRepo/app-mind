# AppMind — Detailed Flow Diagram

Node-by-node view of the LangGraph pipeline: exact routing, the `pipeline_mode` fork, the Critic retry loop, and the AST→GitHub tool-call sequencing. For the simplified component-category view, see [`documentation.md` §3](documentation.md#3-system-design--architecture).

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

    subgraph knowledge["Knowledge and tools"]
        QDRANT[("Qdrant - docs + incidents")]
        AST["Custom AST MCP server (local, offline)"]
        GHMCP["GitHub MCP (remote, incident_rca only)"]
    end

    subgraph storage["Storage"]
        PG[("PostgreSQL - audit trail")]
        REDIS[("Redis - investigation cache")]
    end

    subgraph offlineeval["Evaluation (offline, not live traffic)"]
        JUDGE["LLM-as-Judge"]
        ASTCHECK["Deterministic AST check (Impact Analysis ground truth)"]
    end

    UI -->|"cache-checked"| REDIS
    UI --> IG
    EVALH -->|"27 runs, bypasses cache"| IG
    EVALH --> JUDGE
    EVALH --> ASTCHECK

    RET --> QDRANT
    RET --> AST
    AST -.->|"resolves file path"| GHMCP

    MW --> PG
    MW --> REDIS
```

*Solid arrows are direct calls; dotted arrows are the retry loop and the AST→GitHub file-path handoff. The Evaluation subgraph is offline tooling — it invokes the pipeline the same way the UI does, but is never part of a live request.*