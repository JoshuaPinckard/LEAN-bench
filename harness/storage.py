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
from typing import Any

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
    source                 TEXT NOT NULL,         -- original|quantconnect_forum|qc_docs_example|textbook|paper_reference|other
    is_post_cutoff         INTEGER NOT NULL DEFAULT 0,  -- bool: prompt references post-cutoff LEAN API / market events

    -- categorization
    strategy_type          TEXT,                  -- directional|mean_reversion|derivatives|portfolio|execution|relative_value|other
    strategy_complexity    INTEGER NOT NULL DEFAULT 2,  -- 1=easy|2=medium|3=hard (structural complexity of the strategy logic)
    api_complexity         INTEGER NOT NULL DEFAULT 2,  -- 1=basic|2=intermediate|3=advanced (LEAN API surface required)

    -- LEAN configuration (compressed for analysis)
    securities_type        TEXT,                  -- equity|option|multi_asset
    securities_type_detailed TEXT,               -- equity|forex|crypto|future|option|cfd|mixed (optional detail)
    resolution             TEXT,                  -- high_frequency|intraday|daily
    implementation_type    TEXT,                  -- lean_native|custom_implementation|external_data_required|mixed
    indicators             TEXT,                  -- JSON list[str] of technical indicators referenced
    universe_type          TEXT,                  -- single_asset|multi_asset_specific|index_components|screened_universe|custom_universe_logic
    universe_index         TEXT,                  -- SP500|NASDAQ100|... (when universe_type = index_components)
    universe_index_other   TEXT,                  -- freetext when universe_index = other
    tickers                TEXT,                  -- JSON list[str]
    start_date             TEXT,                  -- ISO date
    end_date               TEXT,
    cash                   INTEGER DEFAULT 100000,

    -- expected behavior / evaluation
    evaluation_mode        TEXT NOT NULL DEFAULT 'trade_required',  -- trade_required|signal_required|code_only|metric_threshold_required
    interpretation_strictness TEXT NOT NULL DEFAULT 'unambiguous',  -- unambiguous|mild_variation|broad_interpretation
    implementation_underspecified INTEGER DEFAULT 0,                -- legacy bool; derived from strictness != 'unambiguous'
    underspecification_notes TEXT,
    excluded_from_benchmark INTEGER NOT NULL DEFAULT 0,  -- bool: curator-flagged out of the benchmark dataset

    -- provenance
    source_date            DATE,                  -- when the strategy idea was first publicly described; NULL if synthetic

    -- AI-assisted curation telemetry (for paper methodology section)
    ai_prepopulated        INTEGER DEFAULT 0,     -- bool: curator used the AI autofill button
    curator_modified_fields TEXT,                 -- JSON list[str]: fields edited after AI fill

    -- leak audit
    leak_audit_status      TEXT NOT NULL DEFAULT 'clean',
    leak_audit_notes       TEXT,

    created_at             TEXT NOT NULL          -- ISO datetime UTC
);

CREATE INDEX IF NOT EXISTS ix_prompts_source ON prompts(source);

CREATE TABLE IF NOT EXISTS runs (
    run_id                   TEXT PRIMARY KEY,
    prompt_id                TEXT REFERENCES prompts(prompt_id),
    model_id                 TEXT,
    model_version            TEXT,
    lean_engine_version      TEXT,
    lean_data_snapshot_hash  TEXT,
    generated_code           TEXT,
    compile_ok               INTEGER,             -- bool 0/1
    backtest_ok              INTEGER,             -- bool 0/1
    trades_count             INTEGER,
    sharpe                   REAL,
    max_drawdown             REAL,
    cagr                     REAL,
    judge_score              REAL,
    judge_reasoning          TEXT,
    judge_replication_index  INTEGER,
    failure_mode             TEXT,                -- NULL until evaluated
    market_regime            TEXT,                -- NULL until enriched
    human_validated          INTEGER DEFAULT 0,  -- bool 0/1
    created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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

    -- snapshot of the documentation snippet appended to the prompt for tool-using
    -- conditions (S2_docs / S3_web / A1_agentic_full); NULL for S1_base.
    retrieval_snippet      TEXT,

    -- error state (NULL on success)
    error                  TEXT,

    FOREIGN KEY (prompt_id) REFERENCES prompts(prompt_id)
);

CREATE INDEX IF NOT EXISTS ix_calls_prompt_id     ON calls(prompt_id);
CREATE INDEX IF NOT EXISTS ix_calls_model_id      ON calls(model_id);
CREATE INDEX IF NOT EXISTS ix_calls_condition     ON calls(condition_id);
-- composite for already_done resumability checks
CREATE UNIQUE INDEX IF NOT EXISTS ux_calls_cell ON calls(prompt_id, model_id, condition_id, trial_index);

-- Retrieval preprocessor cache. Keyed by SHA256 of the raw prompt so the same
-- prompt produces the identical snippet across all 6 models under tool-using
-- conditions, without re-running the Sonnet retrieval calls each time.
CREATE TABLE IF NOT EXISTS retrieval_cache (
    prompt_hash    TEXT PRIMARY KEY,
    prompt_text    TEXT NOT NULL,
    snippet        TEXT NOT NULL,
    model_used     TEXT,
    created_at     TEXT NOT NULL
);

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
        """Idempotently evolve the prompts table for existing DBs.

        Handles two operations:
        - DROP: remove columns that no longer have meaning (difficulty,
          trades_expected). The ix_prompts_difficulty index must be dropped
          first because SQLite won't drop an indexed column.
        - ADD: add new NOT NULL (with defaults) and nullable columns introduced
          in v1.3. All additions are idempotent (skip if column already exists).
        """
        existing = {r["name"] for r in self.conn.execute("PRAGMA table_info(prompts)").fetchall()}

        # --- drops ---
        # difficulty has an index; drop the index first.
        if "difficulty" in existing:
            self.conn.execute("DROP INDEX IF EXISTS ix_prompts_difficulty")
            self.conn.execute("ALTER TABLE prompts DROP COLUMN difficulty")
        if "trades_expected" in existing:
            self.conn.execute("ALTER TABLE prompts DROP COLUMN trades_expected")
        # interpretation_strictness changed from INTEGER -> TEXT enum (v1.4 lock).
        # Drop the integer column so the ADD COLUMN below installs the new TEXT
        # version with the right type and default. Existing prompt rows lose the
        # pre-lock value (they were test data only).
        if "interpretation_strictness" in existing:
            info = self.conn.execute(
                "SELECT type FROM pragma_table_info('prompts') WHERE name='interpretation_strictness'"
            ).fetchone()
            if info and info["type"].upper().startswith("INT"):
                self.conn.execute("ALTER TABLE prompts DROP COLUMN interpretation_strictness")

        # Re-read after drops.
        existing = {r["name"] for r in self.conn.execute("PRAGMA table_info(prompts)").fetchall()}

        # --- adds (format: name -> full DDL fragment appended to ALTER TABLE ADD COLUMN) ---
        add_cols = {
            # v1.4 lock-in (2026-05-13)
            "interpretation_strictness": "TEXT NOT NULL DEFAULT 'unambiguous'",
            "excluded_from_benchmark":  "INTEGER NOT NULL DEFAULT 0",
            # v1.3 new fields
            "strategy_complexity":      "INTEGER NOT NULL DEFAULT 2",
            "api_complexity":           "INTEGER NOT NULL DEFAULT 2",
            "evaluation_mode":          "TEXT NOT NULL DEFAULT 'trade_required'",
            "source_date":              "DATE",
            "implementation_type":      "TEXT",
            "indicators":               "TEXT",
            "universe_type":            "TEXT",
            "universe_index":           "TEXT",
            "universe_index_other":     "TEXT",
            "failure_mode":             "TEXT",
            "failure_notes":            "TEXT",
            "ai_prepopulated":          "INTEGER DEFAULT 0",
            "curator_modified_fields":  "TEXT",
            # v1.2 fields (kept for existing DBs that don't have them yet)
            "securities_type":          "TEXT",
            "securities_type_detailed": "TEXT",
            "resolution":               "TEXT",
            "implementation_underspecified": "INTEGER",
            "underspecification_notes": "TEXT",
            # Retired columns — kept in migration list so re-runs are no-ops
            # on DBs that already have them; new DBs don't get these.
            "primary_failure_mode":            "TEXT",
            "contains_behavioral_ambiguity":   "INTEGER",
            "novelty_level":                   "TEXT",
            "created_after_cutoff":            "INTEGER",
            "references_post_cutoff_event":    "INTEGER",
            "references_post_cutoff_api":      "INTEGER",
            "secondary_failure_modes":         "TEXT",
            "determinism_level":               "TEXT",
            "ambiguity_level":                 "TEXT",
            "underspecified_exit_logic":       "INTEGER",
            "underspecified_risk_management":  "INTEGER",
            "multiple_valid_implementations":  "INTEGER",
        }
        for name, ddl in add_cols.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE prompts ADD COLUMN {name} {ddl}")

        # --- calls table additions ---
        call_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(calls)").fetchall()}
        new_call_cols = {
            # v1.3
            "retrieval_snippet":       "TEXT",
            # v1.4 — locked 35-field calls schema
            "condition":               "TEXT",
            "pass_number":             "INTEGER",
            "retrieval_snippet_hash":  "TEXT",
            "system_prompt_sha":       "TEXT",
            "generated_code":          "TEXT",
            "code_hash":               "TEXT",
            "raw_model_response":      "TEXT",
            "finish_reason":           "TEXT",
            "tokens_in":               "INTEGER",
            "tokens_out":              "INTEGER",
            "cost_usd":                "REAL",
            "latency_ms":              "INTEGER",
            "compile_success":         "INTEGER",
            "runtime_success":         "INTEGER",
            "runtime_error":           "TEXT",
            "lean_results_json":       "TEXT",
            "total_return_pct":        "REAL",
            "sharpe_ratio":            "REAL",
            "max_drawdown_pct":        "REAL",
            "num_trades":              "INTEGER",
            "win_rate":                "REAL",
            "starting_portfolio_value": "REAL",
            "final_portfolio_value":   "REAL",
            "benchmark_return_pct":    "REAL",
            "judge_score":             "REAL",
            "judge_reasoning":         "TEXT",
            "judge_version":           "TEXT",
            "judge_error":             "TEXT",     # exception text when judge fails; NULL on success
            "failure_mode":            "TEXT",     # JSON list[str]
            "failure_notes":           "TEXT",
            "matches_prompt_intent":   "INTEGER",
            "harness_sha":             "TEXT",
            "frozen_date":             "TEXT",
            "created_at":              "TEXT",
        }
        for col, ddl in new_call_cols.items():
            if col not in call_cols:
                self.conn.execute(f"ALTER TABLE calls ADD COLUMN {col} {ddl}")

        # --- deferred indexes (must exist after the columns do) ---
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_prompts_securities_type "
            "ON prompts(securities_type)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_prompts_resolution ON prompts(resolution)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_prompts_strategy_complexity "
            "ON prompts(strategy_complexity)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_prompts_api_complexity "
            "ON prompts(api_complexity)"
        )

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
            "is_post_cutoff", "implementation_underspecified", "ai_prepopulated",
            "excluded_from_benchmark",
        )
        for bcol in bool_cols:
            if bcol in fields:
                fields[bcol] = _b(fields[bcol])
        json_cols = (
            "tickers", "expected_indicators", "expected_order_types",
            "indicators", "failure_mode", "curator_modified_fields",
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

    # ---- retrieval cache -------------------------------------------------

    def get_cached_retrieval(self, prompt_hash: str) -> str | None:
        """Return cached snippet for this prompt hash, or None if not cached.
        Empty string is a valid cached value (means "no relevant docs found")."""
        row = self.conn.execute(
            "SELECT snippet FROM retrieval_cache WHERE prompt_hash=?",
            (prompt_hash,),
        ).fetchone()
        return row["snippet"] if row is not None else None

    def set_cached_retrieval(
        self,
        prompt_hash: str,
        prompt_text: str,
        snippet: str,
        model_used: str | None = None,
    ) -> None:
        """Store the snippet (idempotent upsert)."""
        self.conn.execute(
            "INSERT INTO retrieval_cache(prompt_hash, prompt_text, snippet, model_used, created_at) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(prompt_hash) DO UPDATE SET "
            "snippet=excluded.snippet, model_used=excluded.model_used, created_at=excluded.created_at",
            (prompt_hash, prompt_text, snippet, model_used, _now_utc_iso()),
        )

    # ---- calls -----------------------------------------------------------

    # All bool/JSON columns on `calls` that need normalization on insert/update.
    _CALL_BOOL_COLS = (
        "tool_docs_retrieval", "tool_web_search", "tool_agentic_loop",
        "compile_pass", "backtest_pass", "trade_pass", "judge_pass", "overall_pass",
        "compile_success", "runtime_success", "matches_prompt_intent",
    )
    _CALL_JSON_COLS = ("failure_mode",)

    def _normalize_call_fields(self, fields: dict) -> dict:
        # Mirror condition <-> condition_id so callers can use either name.
        if "condition" in fields and "condition_id" not in fields:
            fields["condition_id"] = fields["condition"]
        if "condition_id" in fields and "condition" not in fields:
            fields["condition"] = fields["condition_id"]
        # Mirror pass_number <-> trial_index.
        if "pass_number" in fields and "trial_index" not in fields:
            fields["trial_index"] = fields["pass_number"]
        if "trial_index" in fields and "pass_number" not in fields:
            fields["pass_number"] = fields["trial_index"]
        # Mirror system_prompt_sha <-> system_prompt_sha256 (old name).
        if "system_prompt_sha" in fields and "system_prompt_sha256" not in fields:
            fields["system_prompt_sha256"] = fields["system_prompt_sha"]
        for bcol in self._CALL_BOOL_COLS:
            if bcol in fields:
                fields[bcol] = _b(fields[bcol])
        for jcol in self._CALL_JSON_COLS:
            if jcol in fields and not isinstance(fields[jcol], (str, type(None))):
                fields[jcol] = _j(fields[jcol])
        return fields

    def record_call(self, **fields) -> str:
        """Append-only insert. Returns call_id (generated if not provided)."""
        fields.setdefault("call_id", str(uuid.uuid4()))
        fields.setdefault("trial_index", 0)
        fields.setdefault("request_timestamp", _now_utc_iso())
        fields.setdefault("created_at", _now_utc_iso())
        self._normalize_call_fields(fields)

        cols = list(fields.keys())
        placeholders = ",".join("?" * len(cols))
        col_list = ",".join(cols)
        sql = f"INSERT INTO calls({col_list}) VALUES({placeholders})"
        self.conn.execute(sql, [fields[c] for c in cols])
        return fields["call_id"]

    def update_call(self, call_id: str, **fields) -> None:
        """Update arbitrary call columns after the fact."""
        if not fields:
            return
        self._normalize_call_fields(fields)
        set_clause = ",".join(f"{c}=?" for c in fields)
        self.conn.execute(
            f"UPDATE calls SET {set_clause} WHERE call_id=?",
            [*fields.values(), call_id],
        )

    # ---- v1.4 staged helpers ---------------------------------------------
    #
    # Three-stage call lifecycle (replaces the single-shot record_call as the
    # canonical path for the locked schema):
    #   create_call                — at generation start (identity + inputs)
    #   update_call_with_backtest  — after LEAN executes (success/metrics)
    #   update_call_with_judge     — after judge scores (overwrites on rejudge)

    def create_call(self, **fields) -> str:
        """Insert a calls row at generation start. Required: prompt_id,
        model_id, condition. Other fields are optional and filled later by
        update_call_with_backtest / update_call_with_judge."""
        fields.setdefault("call_id", str(uuid.uuid4()))
        fields.setdefault("pass_number", 1)
        fields.setdefault("request_timestamp", _now_utc_iso())
        fields.setdefault("created_at", _now_utc_iso())
        # NOT NULL legacy fields need sensible defaults.
        fields.setdefault("tool_docs_retrieval", 0)
        fields.setdefault("tool_web_search", 0)
        fields.setdefault("tool_agentic_loop", 0)
        fields.setdefault("max_turns_allowed", 1)
        fields.setdefault("max_output_tokens", 4096)
        fields.setdefault("system_prompt_sha256", fields.get("system_prompt_sha", ""))
        if "model_version" not in fields:
            fields["model_version"] = fields.get("model_id", "")
        if "model_family" not in fields:
            fields["model_family"] = ""
        self._normalize_call_fields(fields)
        cols = list(fields.keys())
        sql = (
            f"INSERT INTO calls({','.join(cols)}) "
            f"VALUES({','.join('?' * len(cols))})"
        )
        self.conn.execute(sql, [fields[c] for c in cols])
        return fields["call_id"]

    def update_call_with_backtest(
        self,
        call_id: str,
        *,
        compile_success: bool | None,
        runtime_success: bool | None,
        runtime_error: str | None = None,
        lean_results_json: str | None = None,
        total_return_pct: float | None = None,
        sharpe_ratio: float | None = None,
        max_drawdown_pct: float | None = None,
        num_trades: int | None = None,
        win_rate: float | None = None,
        starting_portfolio_value: float | None = None,
        final_portfolio_value: float | None = None,
        benchmark_return_pct: float | None = None,
    ) -> dict:
        """Write backtest fields and derive backtest_pass / trade_pass.

        backtest_pass: True iff the backtest ran end-to-end with no compile
        or runtime error. None when the backtest was skipped (CLI missing,
        timeout, etc.).
        trade_pass: True iff num_trades > 0. Informational only — whether
        no-trades is acceptable depends on prompt.evaluation_mode, which the
        judge already accounts for. None when num_trades is unknown.

        Returns the derived {backtest_pass, trade_pass} so the orchestrator
        can echo them in its response payload."""
        if compile_success is None and runtime_success is None:
            backtest_pass: bool | None = None
        else:
            backtest_pass = bool(compile_success) and bool(runtime_success)

        trade_pass: bool | None = None if num_trades is None else num_trades > 0

        self.update_call(
            call_id,
            compile_success=compile_success,
            runtime_success=runtime_success,
            runtime_error=runtime_error,
            lean_results_json=lean_results_json,
            total_return_pct=total_return_pct,
            sharpe_ratio=sharpe_ratio,
            max_drawdown_pct=max_drawdown_pct,
            num_trades=num_trades,
            win_rate=win_rate,
            starting_portfolio_value=starting_portfolio_value,
            final_portfolio_value=final_portfolio_value,
            benchmark_return_pct=benchmark_return_pct,
            backtest_pass=backtest_pass,
            trade_pass=trade_pass,
        )
        return {"backtest_pass": backtest_pass, "trade_pass": trade_pass}

    def update_call_with_judge(
        self,
        call_id: str,
        *,
        judge_score: float,
        judge_reasoning: str,
        judge_version: str,
        failure_mode: list[str],
        failure_notes: str | None = None,
        matches_prompt_intent: bool,
    ) -> dict:
        """Write judge fields and derive pass_rate inputs. Overwrites any prior
        judge values on re-judge. Returns the derived {judge_pass, overall_pass}
        so callers can echo them back in their response payloads."""
        from harness.constants import JUDGE_PASS_THRESHOLD

        judge_pass = bool(judge_score >= JUDGE_PASS_THRESHOLD)

        # overall_pass also requires the code to compile and (when the backtest
        # ran) to not crash at runtime. When the backtest was skipped — LEAN CLI
        # missing, timeout, etc. — compile_success/runtime_success are NULL and
        # we fall back to the evaluator's AST compile_pass.
        row = self.conn.execute(
            "SELECT compile_pass, compile_success, runtime_success "
            "FROM calls WHERE call_id=?",
            (call_id,),
        ).fetchone()
        compile_pass     = row["compile_pass"]     if row else None
        compile_success  = row["compile_success"]  if row else None
        runtime_success  = row["runtime_success"]  if row else None

        # SQLite stores booleans as integers (0/1), so `is False` would miss them.
        # Use a None-aware falsy check: None means "unknown, fall through".
        def _explicit_fail(v: Any) -> bool:
            return v is not None and not v

        if _explicit_fail(compile_success) or _explicit_fail(runtime_success):
            overall_pass = False
        elif _explicit_fail(compile_pass):
            overall_pass = False
        else:
            overall_pass = judge_pass

        self.update_call(
            call_id,
            judge_score=judge_score,
            judge_reasoning=judge_reasoning,
            judge_version=judge_version,
            failure_mode=failure_mode,
            failure_notes=failure_notes,
            matches_prompt_intent=matches_prompt_intent,
            judge_pass=judge_pass,
            overall_pass=overall_pass,
        )
        return {"judge_pass": judge_pass, "overall_pass": overall_pass}

    def get_calls_by_prompt(self, prompt_id: str) -> list[dict]:
        """All calls for a prompt, ordered by pass_number then created_at."""
        rows = self.conn.execute(
            "SELECT * FROM calls WHERE prompt_id=? "
            "ORDER BY COALESCE(pass_number, trial_index, 0), COALESCE(created_at, request_timestamp)",
            (prompt_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def compute_distribution_stats(self) -> dict:
        """Count prompts (excluding excluded_from_benchmark) along every
        categorical / ordinal field used by the Distribution dashboard.

        Returns a dict shaped:
            {
              "total": int,
              "by_strategy_type": {value: count, ...},
              "by_strategy_complexity": {1: count, ...},
              ...
              "indicator_frequency": {name: count, ...},
            }
        """
        where = "WHERE COALESCE(excluded_from_benchmark, 0) = 0 AND source != 'adhoc'"

        def _count_by(col: str) -> dict:
            rows = self.conn.execute(
                f"SELECT {col} AS k, COUNT(*) AS n FROM prompts {where} GROUP BY {col}"
            ).fetchall()
            out: dict = {}
            for r in rows:
                key = r["k"]
                if key is None:
                    key = "__null__"
                out[str(key)] = int(r["n"])
            return out

        total = int(self.conn.execute(
            f"SELECT COUNT(*) AS n FROM prompts {where}"
        ).fetchone()["n"])

        # Indicator frequency: JSON array column needs row-level decode.
        indicator_freq: dict[str, int] = {}
        for r in self.conn.execute(
            f"SELECT indicators FROM prompts {where} AND indicators IS NOT NULL"
        ).fetchall():
            raw = r["indicators"]
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(parsed, list):
                continue
            for item in parsed:
                # accept {name, params} or bare string
                name = item.get("name") if isinstance(item, dict) else str(item)
                if name:
                    indicator_freq[name] = indicator_freq.get(name, 0) + 1

        return {
            "total":                    total,
            "by_strategy_type":         _count_by("strategy_type"),
            "by_strategy_complexity":   _count_by("strategy_complexity"),
            "by_api_complexity":        _count_by("api_complexity"),
            "by_implementation_type":   _count_by("implementation_type"),
            "by_universe_type":         _count_by("universe_type"),
            "by_securities_type":       _count_by("securities_type"),
            "by_resolution":            _count_by("resolution"),
            "by_evaluation_mode":       _count_by("evaluation_mode"),
            "by_interpretation_strictness": _count_by("interpretation_strictness"),
            "indicator_frequency":      indicator_freq,
        }

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

    def __exit__(self, *_) -> None:
        self.close()
