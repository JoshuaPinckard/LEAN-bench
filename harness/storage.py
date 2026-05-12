"""SQLite layer for LEAN-Bench. Three normalized tables: prompts, calls, turns.

Schema is locked at v1.0 — never add columns mid-experiment. New analysis
dimensions go in derived tables or the per-call JSON at trajectory_path.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1.0"

DEFAULT_DB_PATH = Path("results/leanbench.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompts (
    -- identifiers
    prompt_id              TEXT PRIMARY KEY,
    version                TEXT NOT NULL,

    -- text
    original_text          TEXT NOT NULL,
    original_url           TEXT,
    reformulated_text      TEXT NOT NULL,
    reformulation_notes    TEXT,

    -- provenance
    source                 TEXT NOT NULL,         -- qc_forum|qc_docs|reddit|stackexchange|github|tradingview|original
    source_creation_date   TEXT,                  -- ISO date, NULL for synthetic
    source_license         TEXT,                  -- SPDX identifier

    -- difficulty & categorization
    difficulty             TEXT NOT NULL,         -- easy|medium|hard
    difficulty_rubric_match TEXT,
    strategy_type          TEXT,                  -- trend_following|mean_reversion|momentum|...

    -- LEAN-specific eval metadata
    qc_securities_type     TEXT,                  -- equity|forex|crypto|future|option|...
    qc_universe_type       TEXT,                  -- manual|dynamic_coarse|dynamic_coarse_fine
    qc_data_resolution     TEXT,                  -- tick|second|minute|hour|daily
    qc_brokerage_model     TEXT,                  -- default|interactivebrokers|alpaca|...
    tickers                TEXT,                  -- JSON list[str]
    start_date             TEXT,                  -- ISO date
    end_date               TEXT,
    cash                   INTEGER DEFAULT 100000,

    -- expected behavior
    trades_expected        INTEGER NOT NULL,      -- bool 0/1
    expected_indicators    TEXT,                  -- JSON list[{name, params}] (legacy: list[str])
    expected_order_types   TEXT,                  -- JSON list[str]

    -- evaluation metadata
    primary_failure_mode   TEXT,                  -- curator's target failure mode (see FAILURE_MODES in PromptModal)
    contains_behavioral_ambiguity INTEGER,        -- bool: prompt admits multiple meaningfully different implementations
    novelty_level          TEXT,                  -- canonical|modified_canonical|original_novel|post_cutoff_reference

    -- leak audit
    leak_audit_status      TEXT NOT NULL,         -- clean|flagged|manually_cleared|rejected
    leak_audit_notes       TEXT,

    created_at             TEXT NOT NULL          -- ISO datetime UTC
);

CREATE INDEX IF NOT EXISTS ix_prompts_source     ON prompts(source);
CREATE INDEX IF NOT EXISTS ix_prompts_difficulty ON prompts(difficulty);
CREATE INDEX IF NOT EXISTS ix_prompts_post_cutoff ON prompts(is_post_cutoff);

CREATE TABLE IF NOT EXISTS calls (
    -- identifiers
    call_id                TEXT PRIMARY KEY,      -- UUIDv4
    prompt_id              TEXT NOT NULL,
    model_family           TEXT NOT NULL,         -- claude|gpt|gemini
    model_id               TEXT NOT NULL,         -- friendly name from MODELS_FROZEN
    model_version          TEXT NOT NULL,         -- exact API string used
    condition_id           TEXT NOT NULL,         -- S1_base|S2_docs|S3_web|A1_agentic_full
    trial_index            INTEGER NOT NULL DEFAULT 0,  -- 0 main grid, 0..3 variance subset

    -- decomposed tool flags (redundant with condition_id, for query-friendliness)
    tool_docs_retrieval    INTEGER NOT NULL,      -- bool 0/1
    tool_web_search        INTEGER NOT NULL,
    tool_agentic_loop      INTEGER NOT NULL,
    max_turns_allowed      INTEGER NOT NULL,

    -- request metadata
    temperature            REAL NOT NULL DEFAULT 0.0,
    top_p                  REAL NOT NULL DEFAULT 1.0,
    max_output_tokens      INTEGER NOT NULL,
    system_prompt_sha256   TEXT NOT NULL,
    request_timestamp      TEXT NOT NULL,         -- ISO datetime UTC

    -- aggregate results
    turns_used             INTEGER,
    final_code_sha256      TEXT,

    -- four-stage pipeline outcomes (NULL until evaluated)
    compile_pass           INTEGER,
    backtest_pass          INTEGER,
    trade_pass             INTEGER,
    judge_pass             INTEGER,
    overall_pass           INTEGER,
    first_failed_stage     TEXT,                  -- compile|backtest|trade|judge|NULL
    failure_category_l1    TEXT,                  -- top-level taxonomy
    failure_category_l2    TEXT,                  -- subcategory

    -- cost / observability
    total_input_tokens     INTEGER,
    total_output_tokens    INTEGER,
    total_cost_usd         REAL,
    wall_clock_seconds     REAL,

    -- raw trajectory pointer (full transcript lives in JSON next to DB)
    trajectory_path        TEXT,

    -- error state (NULL on success)
    error                  TEXT,

    FOREIGN KEY (prompt_id) REFERENCES prompts(prompt_id)
);

CREATE INDEX IF NOT EXISTS ix_calls_prompt_id     ON calls(prompt_id);
CREATE INDEX IF NOT EXISTS ix_calls_model_id      ON calls(model_id);
CREATE INDEX IF NOT EXISTS ix_calls_condition     ON calls(condition_id);
-- composite for already_done resumability checks
CREATE UNIQUE INDEX IF NOT EXISTS ux_calls_cell ON calls(prompt_id, model_id, condition_id, trial_index);

CREATE TABLE IF NOT EXISTS turns (
    turn_id                TEXT PRIMARY KEY,      -- UUIDv4
    call_id                TEXT NOT NULL,
    turn_index             INTEGER NOT NULL,      -- 0-indexed within call

    -- request portion
    prompt_messages_json   TEXT NOT NULL,
    retrieval_queries      TEXT,                  -- JSON list[str]
    retrieval_doc_ids      TEXT,                  -- JSON list[str]
    web_search_queries     TEXT,                  -- JSON list[str]
    web_search_result_urls TEXT,                  -- JSON list[str]

    -- response portion
    response_text          TEXT NOT NULL,
    response_code_extracted TEXT,                 -- parsed code block, if present
    response_tokens_in     INTEGER,
    response_tokens_out    INTEGER,

    -- per-turn pipeline outcome (only meaningful for A1_agentic_full)
    ran_pipeline           INTEGER NOT NULL,      -- bool
    compile_pass           INTEGER,               -- nullable bool
    backtest_pass          INTEGER,
    trade_pass             INTEGER,
    judge_pass             INTEGER,
    feedback_text          TEXT,                  -- structured feedback sent back to model

    cost_usd               REAL,
    wall_clock_seconds     REAL,

    FOREIGN KEY (call_id) REFERENCES calls(call_id)
);

CREATE INDEX IF NOT EXISTS ix_turns_call_id ON turns(call_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_turns_call_turn ON turns(call_id, turn_index);
"""


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _b(value: bool | None) -> int | None:
    """Bool -> SQLite INTEGER (None passes through)."""
    if value is None:
        return None
    return 1 if value else 0


def _j(value: Any) -> str | None:
    """JSON-encode lists/dicts for TEXT storage; None passes through."""
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"))


class Store:
    """SQLite store. Crash-safe (WAL mode), idempotent inserts where it matters."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # check_same_thread=False: FastAPI runs sync handlers in a thread pool,
        # so each request arrives on a different thread. WAL mode makes
        # concurrent reads safe; writes are serialised by SQLite's locking.
        self.conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")

        self.conn.executescript(SCHEMA)
        self._migrate_add_columns()
        self._set_meta("schema_version", SCHEMA_VERSION)

    def _migrate_add_columns(self) -> None:
        """Idempotently add nullable columns introduced after the initial v1.0
        cut. SQLite's CREATE TABLE IF NOT EXISTS only handles new DBs; existing
        DBs need explicit ALTER TABLE. All adds are nullable so prior rows
        receive NULL — no data is mutated.
        """
        new_cols: dict[str, dict[str, str]] = {
            "prompts": {
                # v1.1 additions (2026-05-12): streamlined evaluation metadata
                "primary_failure_mode":           "TEXT",
                "contains_behavioral_ambiguity":  "INTEGER",
                "novelty_level":                  "TEXT",
                # Earlier columns that were added and then retired; left in
                # migration so existing DBs don't re-apply, but not written by
                # current code. New DBs won't have these at all.
                "created_after_cutoff":           "INTEGER",
                "references_post_cutoff_event":   "INTEGER",
                "references_post_cutoff_api":     "INTEGER",
                "evaluation_mode":                "TEXT",
                "secondary_failure_modes":        "TEXT",
                "determinism_level":              "TEXT",
                "ambiguity_level":                "TEXT",
                "underspecified_exit_logic":      "INTEGER",
                "underspecified_risk_management": "INTEGER",
                "multiple_valid_implementations": "INTEGER",
            },
        }
        for table, cols in new_cols.items():
            existing = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for name, ddl in cols.items():
                if name not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    # ---- meta ------------------------------------------------------------

    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM schema_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    # ---- prompts ---------------------------------------------------------

    def add_prompt(self, **fields) -> str:
        """Idempotent upsert by prompt_id. Returns prompt_id."""
        fields.setdefault("created_at", _now_utc_iso())
        fields.setdefault("version", "1.0.0")

        # bool/list normalization
        bool_cols = (
            "trades_expected", "is_post_cutoff", "contains_behavioral_ambiguity",
        )
        for bcol in bool_cols:
            if bcol in fields:
                fields[bcol] = _b(fields[bcol])
        json_cols = (
            "tickers", "expected_indicators", "expected_order_types",
        )
        for jcol in json_cols:
            if jcol in fields and not isinstance(fields[jcol], (str, type(None))):
                fields[jcol] = _j(fields[jcol])

        cols = list(fields.keys())
        placeholders = ",".join("?" * len(cols))
        col_list = ",".join(cols)
        update_clause = ",".join(f"{c}=excluded.{c}" for c in cols if c != "prompt_id")

        sql = (
            f"INSERT INTO prompts({col_list}) VALUES({placeholders}) "
            f"ON CONFLICT(prompt_id) DO UPDATE SET {update_clause}"
        )
        self.conn.execute(sql, [fields[c] for c in cols])
        return fields["prompt_id"]

    def get_prompt(self, prompt_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM prompts WHERE prompt_id=?", (prompt_id,)).fetchone()
        return dict(row) if row else None

    def list_prompts(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM prompts ORDER BY prompt_id").fetchall()
        return [dict(r) for r in rows]

    # ---- calls -----------------------------------------------------------

    def already_done(
        self,
        prompt_id: str,
        model_id: str,
        condition_id: str,
        trial_index: int = 0,
    ) -> bool:
        """Resumability check before firing an API call."""
        row = self.conn.execute(
            "SELECT 1 FROM calls WHERE prompt_id=? AND model_id=? AND condition_id=? AND trial_index=?",
            (prompt_id, model_id, condition_id, trial_index),
        ).fetchone()
        return row is not None

    def next_trial_index(
        self,
        prompt_id: str,
        model_id: str,
        condition_id: str,
    ) -> int:
        """Next free trial_index for this cell. Lets the dev UI re-run a
        cell without violating the unique constraint; batch scripts that want
        idempotent resumability use already_done() instead."""
        row = self.conn.execute(
            "SELECT COALESCE(MAX(trial_index), -1) + 1 AS n "
            "FROM calls WHERE prompt_id=? AND model_id=? AND condition_id=?",
            (prompt_id, model_id, condition_id),
        ).fetchone()
        return int(row["n"])

    def delete_prompt(self, prompt_id: str) -> int:
        """Delete a prompt and cascade to its calls and turns. Returns deleted call count."""
        call_ids = [
            r["call_id"] for r in self.conn.execute(
                "SELECT call_id FROM calls WHERE prompt_id=?", (prompt_id,)
            ).fetchall()
        ]
        for cid in call_ids:
            self.conn.execute("DELETE FROM turns WHERE call_id=?", (cid,))
        self.conn.execute("DELETE FROM calls WHERE prompt_id=?", (prompt_id,))
        self.conn.execute("DELETE FROM prompts WHERE prompt_id=?", (prompt_id,))
        return len(call_ids)

    def search_prompts(
        self,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_adhoc: bool = False,
    ) -> tuple[list[dict], int]:
        """Paginated prompt list with optional fulltext-ish search on
        reformulated_text. Returns (rows, total_matching_count)."""
        where = []
        params: list = []
        if not include_adhoc:
            where.append("source != 'adhoc'")
        if search:
            where.append("reformulated_text LIKE ?")
            params.append(f"%{search}%")
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        total = int(self.conn.execute(
            f"SELECT COUNT(*) AS n FROM prompts {where_clause}", params
        ).fetchone()["n"])

        rows = self.conn.execute(
            f"SELECT * FROM prompts {where_clause} ORDER BY prompt_id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total

    def next_prompt_id(self, prefix: str = "lb") -> str:
        """Generate the next sequential prompt_id like 'lb-0042' (4-digit padded)."""
        row = self.conn.execute(
            "SELECT prompt_id FROM prompts WHERE prompt_id LIKE ? "
            "ORDER BY prompt_id DESC LIMIT 1",
            (f"{prefix}-%",),
        ).fetchone()
        if not row:
            return f"{prefix}-0001"
        try:
            n = int(row["prompt_id"].split("-")[-1])
        except (ValueError, IndexError):
            n = 0
        return f"{prefix}-{n + 1:04d}"

    def pass_rate_matrix(self) -> list[dict]:
        """Per-cell judge_pass rate. Returns rows of {model_id, condition_id, n, pass_rate}.
        pass_rate is None when no calls have judge_pass populated yet."""
        rows = self.conn.execute("""
            SELECT model_id, condition_id,
                   COUNT(*) AS n,
                   AVG(CASE WHEN judge_pass IS NULL THEN NULL
                            ELSE judge_pass END) AS pass_rate
            FROM calls
            GROUP BY model_id, condition_id
        """).fetchall()
        out = []
        for r in rows:
            pr = r["pass_rate"]
            out.append({
                "model_id": r["model_id"],
                "condition_id": r["condition_id"],
                "n": int(r["n"]),
                "pass_rate": float(pr) if pr is not None else None,
            })
        return out

    def record_call(self, **fields) -> str:
        """Append-only insert. Returns call_id (generated if not provided)."""
        fields.setdefault("call_id", str(uuid.uuid4()))
        fields.setdefault("trial_index", 0)
        fields.setdefault("request_timestamp", _now_utc_iso())

        for bcol in (
            "tool_docs_retrieval", "tool_web_search", "tool_agentic_loop",
            "compile_pass", "backtest_pass", "trade_pass", "judge_pass", "overall_pass",
        ):
            if bcol in fields:
                fields[bcol] = _b(fields[bcol])

        cols = list(fields.keys())
        placeholders = ",".join("?" * len(cols))
        col_list = ",".join(cols)
        sql = f"INSERT INTO calls({col_list}) VALUES({placeholders})"
        self.conn.execute(sql, [fields[c] for c in cols])
        return fields["call_id"]

    def update_call(self, call_id: str, **fields) -> None:
        """Update evaluation columns after the fact (eval is separate from generation)."""
        for bcol in (
            "compile_pass", "backtest_pass", "trade_pass", "judge_pass", "overall_pass",
        ):
            if bcol in fields:
                fields[bcol] = _b(fields[bcol])

        if not fields:
            return
        set_clause = ",".join(f"{c}=?" for c in fields)
        self.conn.execute(
            f"UPDATE calls SET {set_clause} WHERE call_id=?",
            [*fields.values(), call_id],
        )

    def get_call(self, call_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM calls WHERE call_id=?", (call_id,)).fetchone()
        return dict(row) if row else None

    def calls_for_prompt(self, prompt_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM calls WHERE prompt_id=? ORDER BY request_timestamp",
            (prompt_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- turns -----------------------------------------------------------

    def record_turn(self, **fields) -> str:
        fields.setdefault("turn_id", str(uuid.uuid4()))
        for bcol in ("ran_pipeline", "compile_pass", "backtest_pass", "trade_pass", "judge_pass"):
            if bcol in fields:
                fields[bcol] = _b(fields[bcol])
        for jcol in ("retrieval_queries", "retrieval_doc_ids", "web_search_queries", "web_search_result_urls"):
            if jcol in fields and not isinstance(fields[jcol], (str, type(None))):
                fields[jcol] = _j(fields[jcol])

        cols = list(fields.keys())
        placeholders = ",".join("?" * len(cols))
        col_list = ",".join(cols)
        sql = f"INSERT INTO turns({col_list}) VALUES({placeholders})"
        self.conn.execute(sql, [fields[c] for c in cols])
        return fields["turn_id"]

    def turns_for_call(self, call_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM turns WHERE call_id=? ORDER BY turn_index",
            (call_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- aggregations ----------------------------------------------------

    def total_cost_usd(self) -> float:
        row = self.conn.execute("SELECT COALESCE(SUM(total_cost_usd), 0.0) AS s FROM calls").fetchone()
        return float(row["s"])

    def call_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM calls").fetchone()
        return int(row["n"])

    def cost_by_model(self) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT model_id, COALESCE(SUM(total_cost_usd), 0.0) AS s "
            "FROM calls GROUP BY model_id"
        ).fetchall()
        return {r["model_id"]: float(r["s"]) for r in rows}

    def cost_by_condition(self) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT condition_id, COALESCE(SUM(total_cost_usd), 0.0) AS s "
            "FROM calls GROUP BY condition_id"
        ).fetchall()
        return {r["condition_id"]: float(r["s"]) for r in rows}

    def recent_calls(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM calls ORDER BY request_timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- lifecycle -------------------------------------------------------

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
