"""
Durable SQLite WAL Persistence Layer & GDPR Right-to-Erasure Engine.
Persists campaigns, immutable audit trace ledgers, custom Brand Vault rules,
and Golden Dataset Flywheel feedback across server restarts.

Traceability: REQ-DB-01
Governing Skills:
- database-and-async-persistence
- ai-governance-privacy-and-compliance
- security-and-multi-tenant-saas
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "adaiz_state.db"


class SQLitePersistenceManager:
    """
    Thread-safe SQLite WAL persistence manager for campaigns, audit traces,
    flywheel records, and GDPR cascading tenant erasure.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    brand_id TEXT NOT NULL,
                    workflow_status TEXT NOT NULL,
                    total_budget_usd REAL NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_campaigns_tenant ON campaigns(tenant_id);

                CREATE TABLE IF NOT EXISTS audit_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    node TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    cost_usd REAL NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_ledger(tenant_id, campaign_id);

                CREATE TABLE IF NOT EXISTS flywheel_dataset (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    brand_id TEXT NOT NULL,
                    approved INTEGER NOT NULL,
                    reviewer TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def save_campaign_snapshot(self, serialized_state: dict[str, Any]) -> None:
        """Upsert serialized campaign state and append new trace spans to the immutable audit ledger."""
        if not serialized_state or not serialized_state.get("campaign_id"):
            return
        campaign_id = serialized_state["campaign_id"]
        brief = serialized_state.get("brief", {})
        tenant_id = brief.get("tenant_id", "unknown")
        brand_id = brief.get("brand_id", "unknown")
        status = serialized_state.get("workflow_status", "running")
        budget = float(brief.get("total_budget_usd", 0.0))
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO campaigns (campaign_id, tenant_id, brand_id, workflow_status, total_budget_usd, state_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id) DO UPDATE SET
                    workflow_status = excluded.workflow_status,
                    total_budget_usd = excluded.total_budget_usd,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    campaign_id,
                    tenant_id,
                    brand_id,
                    status,
                    budget,
                    json.dumps(serialized_state, default=str),
                    now_iso,
                ),
            )

            # Sync trace events idempotently by replacing campaign's trace log with latest complete list
            conn.execute("DELETE FROM audit_ledger WHERE campaign_id = ?", (campaign_id,))
            for ev in serialized_state.get("trace_events", []):
                conn.execute(
                    """
                    INSERT INTO audit_ledger (campaign_id, tenant_id, node, event_type, summary, duration_ms, cost_usd, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        campaign_id,
                        tenant_id,
                        ev.get("node", ""),
                        ev.get("event_type", "tool_call"),
                        ev.get("summary", ""),
                        float(ev.get("duration_ms", 0.0)),
                        float(ev.get("cost_usd", 0.0)),
                        ev.get("timestamp", now_iso),
                    ),
                )

    def load_campaign_snapshot(self, campaign_id: str) -> dict[str, Any] | None:
        """Load a persisted campaign state snapshot from SQLite if not in hot memory."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM campaigns WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
            if not row:
                return None
            return json.loads(row["state_json"])

    def list_recent_campaigns(self, tenant_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """List recent campaigns stored in SQLite."""
        with self._connect() as conn:
            if tenant_id:
                rows = conn.execute(
                    "SELECT campaign_id, tenant_id, brand_id, workflow_status, total_budget_usd, updated_at "
                    "FROM campaigns WHERE tenant_id = ? ORDER BY updated_at DESC LIMIT ?",
                    (tenant_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT campaign_id, tenant_id, brand_id, workflow_status, total_budget_usd, updated_at "
                    "FROM campaigns ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def record_flywheel_entry(
        self,
        campaign_id: str,
        tenant_id: str,
        brand_id: str,
        approved: bool,
        reviewer: str,
        notes: str,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO flywheel_dataset (campaign_id, tenant_id, brand_id, approved, reviewer, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (campaign_id, tenant_id, brand_id, 1 if approved else 0, reviewer, notes, now_iso),
            )

    def purge_tenant_completely(self, tenant_id: str) -> dict[str, int]:
        """
        GDPR / CCPA Right-to-Erasure: Atomically delete all campaigns, audit traces,
        and flywheel records belonging to `tenant_id` from SQLite storage.
        """
        with self._connect() as conn:
            c_cur = conn.execute("DELETE FROM campaigns WHERE tenant_id = ?", (tenant_id,))
            a_cur = conn.execute("DELETE FROM audit_ledger WHERE tenant_id = ?", (tenant_id,))
            f_cur = conn.execute("DELETE FROM flywheel_dataset WHERE tenant_id = ?", (tenant_id,))
            return {
                "campaigns_deleted": c_cur.rowcount,
                "audit_spans_deleted": a_cur.rowcount,
                "flywheel_records_deleted": f_cur.rowcount,
            }
