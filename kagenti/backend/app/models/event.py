# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
SQLAlchemy-style event table schema for per-event persistence.

Events are stored individually (one row per SSE event) instead of as a
blob in task metadata. This enables paginated retrieval, turn-level
loading, and efficient history reconstruction.

Uses raw asyncpg (matching session_db.py pattern) rather than SQLAlchemy
ORM, because the sessions database is managed via asyncpg pools.
"""

# Schema DDL — executed via _ensure_events_schema() on pool creation.
EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    context_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    event_index INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_category TEXT,
    langgraph_node TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (context_id, task_id, event_index)
);
CREATE INDEX IF NOT EXISTS idx_events_ctx_idx ON events(context_id, event_index);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, event_index);
"""
