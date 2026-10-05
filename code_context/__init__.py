"""
code_context — AppMind's read-only view of the code knowledge store.

The store is written by a separate project (indexer/), which AppMind never
imports. The only interface between them is the data documented in
indexer/CONTRACT.md. This package is the one place AppMind knows that
contract: it reads snapshots, checks their schema version, and rebuilds the
dependency graph so questions about it can be answered.
"""
