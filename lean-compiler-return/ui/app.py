"""Tkinter test harness for lean_backtest_tool.

Layout:
    Top:    controls (language, fixture loader, workdir, data dir, image,
            mock toggle, Run).
    Middle: paned window — code editor | output notebook with three tabs
            (Filtered (what model sees) / Raw log / Diff).
    Bottom: status bar (exit_status, wall-clock, token count).

This file is NOT part of the published package. Removing the `ui/` directory
removes everything UI-related; the library has no reverse dependency.

Run:
    python -m ui.app

Mock mode (default ON until you have Docker + the pinned LEAN image ready)
swaps the runner's Docker invoker for a canned-log invoker so you can see
filter behavior immediately, without a Docker round-trip.
"""
from __future__ import annotations

import difflib
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lean_backtest_tool import RunConfig, run, runner, spec_constants  # noqa: E402
from lean_backtest_tool.log_filter import filter_log  # noqa: E402
from ui.mock_invoker import MockInvoker  # noqa: E402


PYTHON_FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "python"
CSHARP_FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "csharp"
DEFAULT_WORKDIR = REPO_ROOT / "ui" / ".workdir"
DEFAULT_DATA_DIR = REPO_ROOT / "data"  # populated by `lean init` at repo root


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("lean_backtest_tool — test harness")
        root.geometry("1400x900")

        self.language_var = tk.StringVar(value="python")
        self.fixture_var = tk.StringVar(value="(custom)")
        self.workdir_var = tk.StringVar(value=str(DEFAULT_WORKDIR))
        self.data_dir_var = tk.StringVar(value=str(DEFAULT_DATA_DIR))
        self.image_var = tk.StringVar(value=spec_constants.DEFAULT_DOCKER_IMAGE)
        self.mock_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="ready")

        self._raw_log_cache: str = ""
        self._filtered_cache: str = ""

        self._build_layout()
        self._refresh_fixture_list()
        # Load a sensible default fixture so the editor isn't empty.
        self.fixture_var.set("compiles_no_trades.py")
        self._load_selected_fixture()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        mono = font.nametofont("TkFixedFont")
        mono.configure(size=10)

        controls = ttk.Frame(self.root, padding=8)
        controls.pack(side=tk.TOP, fill=tk.X)

        # Row 1: language + fixture loader
        row1 = ttk.Frame(controls)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Language:").pack(side=tk.LEFT)
        ttk.Radiobutton(
            row1, text="Python", value="python",
            variable=self.language_var, command=self._on_language_change,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(
            row1, text="C#", value="csharp",
            variable=self.language_var, command=self._on_language_change,
        ).pack(side=tk.LEFT, padx=4)

        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=12)

        ttk.Label(row1, text="Fixture:").pack(side=tk.LEFT)
        self.fixture_combo = ttk.Combobox(
            row1, textvariable=self.fixture_var, width=36, state="readonly",
        )
        self.fixture_combo.pack(side=tk.LEFT, padx=4)
        ttk.Button(row1, text="Load", command=self._load_selected_fixture).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="Clear", command=self._clear_editor).pack(side=tk.LEFT, padx=2)

        # Row 2: workdir + data dir
        row2 = ttk.Frame(controls)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Workdir:").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.workdir_var, width=42).pack(side=tk.LEFT, padx=4)
        ttk.Button(row2, text="…", width=2,
                   command=lambda: self._pick_dir(self.workdir_var)).pack(side=tk.LEFT)

        ttk.Label(row2, text="  Data dir:").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Entry(row2, textvariable=self.data_dir_var, width=42).pack(side=tk.LEFT, padx=4)
        ttk.Button(row2, text="…", width=2,
                   command=lambda: self._pick_dir(self.data_dir_var)).pack(side=tk.LEFT)

        # Row 3: image + mock + run
        row3 = ttk.Frame(controls)
        row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="Docker image:").pack(side=tk.LEFT)
        ttk.Entry(row3, textvariable=self.image_var, width=50).pack(side=tk.LEFT, padx=4)

        ttk.Checkbutton(
            row3, text="Mock (no Docker)", variable=self.mock_var,
        ).pack(side=tk.LEFT, padx=12)

        self.run_button = ttk.Button(row3, text="Run Backtest", command=self._on_run_clicked)
        self.run_button.pack(side=tk.RIGHT, padx=4)

        # Main paned window
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Left: code editor
        left = ttk.Frame(paned)
        ttk.Label(left, text="Algorithm source", font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W)
        self.editor = tk.Text(left, wrap=tk.NONE, undo=True, font=mono)
        editor_y = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.editor.yview)
        editor_x = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.editor.xview)
        self.editor.configure(yscrollcommand=editor_y.set, xscrollcommand=editor_x.set)
        editor_y.pack(side=tk.RIGHT, fill=tk.Y)
        editor_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.editor.pack(fill=tk.BOTH, expand=True)
        paned.add(left, weight=1)

        # Right: output notebook
        right = ttk.Frame(paned)
        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: filtered output (what the model sees)
        self.filtered_text = self._make_text_tab(self.notebook, "Filtered (model sees this)", mono)
        # Tab 2: raw log
        self.raw_text = self._make_text_tab(self.notebook, "Raw log", mono)
        # Tab 3: diff of raw vs filtered (so the filter behavior is visible)
        self.diff_text = self._make_text_tab(self.notebook, "Diff (kept vs dropped)", mono)
        paned.add(right, weight=1)

        # Status bar
        status = ttk.Frame(self.root, padding=(8, 2))
        status.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(status, textvariable=self.status_var, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(status, text="Copy filtered output",
                   command=self._copy_filtered_to_clipboard).pack(side=tk.RIGHT)

    def _make_text_tab(self, notebook: ttk.Notebook, title: str, mono) -> tk.Text:
        frame = ttk.Frame(notebook)
        text = tk.Text(frame, wrap=tk.NONE, font=mono)
        y = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        x = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=y.set, xscrollcommand=x.set, state=tk.DISABLED)
        y.pack(side=tk.RIGHT, fill=tk.Y)
        x.pack(side=tk.BOTTOM, fill=tk.X)
        text.pack(fill=tk.BOTH, expand=True)
        notebook.add(frame, text=title)
        # tag colors for the diff view
        text.tag_configure("kept", foreground="#1b6e1b")
        text.tag_configure("dropped", foreground="#a13030", overstrike=True)
        return text

    # ------------------------------------------------------------------
    # Fixture handling
    # ------------------------------------------------------------------

    def _refresh_fixture_list(self) -> None:
        lang = self.language_var.get()
        if lang == "python":
            fixtures = sorted(p.name for p in PYTHON_FIXTURES_DIR.glob("*.py"))
        else:
            fixtures = sorted(p.name for p in CSHARP_FIXTURES_DIR.glob("Main_*.cs"))
        self.fixture_combo["values"] = ["(custom)"] + fixtures

    def _on_language_change(self) -> None:
        self._refresh_fixture_list()
        self.fixture_var.set("(custom)")

    def _load_selected_fixture(self) -> None:
        name = self.fixture_var.get()
        if not name or name == "(custom)":
            return
        lang = self.language_var.get()
        path = (PYTHON_FIXTURES_DIR if lang == "python" else CSHARP_FIXTURES_DIR) / name
        if not path.exists():
            messagebox.showerror("Fixture not found", f"{path} does not exist")
            return
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            messagebox.showerror("Read failed", str(e))
            return
        self._set_editor(content)
        self._set_status(f"loaded {name} ({len(content)} bytes)")

    def _clear_editor(self) -> None:
        self._set_editor("")

    def _set_editor(self, text: str) -> None:
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", text)

    def _editor_contents(self) -> str:
        return self.editor.get("1.0", tk.END).rstrip("\n") + "\n"

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    def _pick_dir(self, var: tk.StringVar) -> None:
        current = var.get()
        chosen = filedialog.askdirectory(initialdir=current if Path(current).is_dir() else None)
        if chosen:
            var.set(chosen)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _write_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        widget.configure(state=tk.DISABLED)

    def _write_diff(self, raw: str, filtered: str) -> None:
        """Render raw log with kept lines green and dropped lines struck-through.

        This is approximate — we recompute the filter line-by-line so we can
        annotate each raw line as kept/dropped. Matches log_filter.filter_log
        logic so the displayed diff is the actual filter behavior.
        """
        widget = self.diff_text
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)

        # Recompute per-line keep/drop by piggybacking on filter_log: easiest
        # is to feed lines individually and check membership.
        inherited = None
        for line in raw.splitlines():
            m = spec_constants.TAG_PATTERN.search(line)
            tag = m.group(1) if m else None
            effective = tag if tag is not None else inherited
            if effective is None:
                kept = spec_constants.UNTAGGED_PREFIX_POLICY == "keep"
            elif effective in spec_constants.DROPPED_TAGS:
                kept = False
            elif effective in spec_constants.KEPT_TAGS:
                kept = True
            else:
                kept = spec_constants.UNKNOWN_TAG_POLICY == "keep"
            if tag is not None:
                inherited = tag
            tag_name = "kept" if kept else "dropped"
            widget.insert(tk.END, line + "\n", tag_name)

        widget.configure(state=tk.DISABLED)
        _ = filtered  # the recomputation above is authoritative

    def _copy_filtered_to_clipboard(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self._filtered_cache)
        self._set_status("filtered output copied to clipboard")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def _on_run_clicked(self) -> None:
        code = self._editor_contents()
        if not code.strip():
            messagebox.showwarning("Empty editor", "Type or load some code first.")
            return

        language = self.language_var.get()
        workdir = self.workdir_var.get()
        data_dir = self.data_dir_var.get()
        image = self.image_var.get()
        mock = self.mock_var.get()

        Path(workdir).mkdir(parents=True, exist_ok=True)
        if mock:
            Path(data_dir).mkdir(parents=True, exist_ok=True)
        elif not Path(data_dir).is_dir():
            messagebox.showerror(
                "Data dir missing",
                f"{data_dir} does not exist. Either point to a real LEAN data folder "
                "or enable Mock mode.",
            )
            return

        self.run_button.configure(state=tk.DISABLED)
        self._set_status("running…")
        thread = threading.Thread(
            target=self._run_backtest_thread,
            args=(code, language, workdir, data_dir, image, mock),
            daemon=True,
        )
        thread.start()

    def _run_backtest_thread(
        self,
        code: str,
        language: str,
        workdir: str,
        data_dir: str,
        image: str,
        mock: bool,
    ) -> None:
        start = time.monotonic()
        if mock:
            runner.set_invoker(MockInvoker())
        else:
            runner.reset_invoker()

        try:
            cfg = RunConfig(
                workdir=workdir, lean_data_dir=data_dir, docker_image=image,
            )
            result = run(code, language, cfg)
            elapsed = time.monotonic() - start

            # The runner ate the raw log on its way out; refilter for the
            # diff view by reading the canned/captured log. We don't have it
            # exposed directly via RunResult by design (the model only sees
            # `output`). For the diff tab we approximate by re-deriving from
            # the cleanup-deleted project dir is impossible, so we use the
            # mock_invoker's canned log when in mock mode, else fall back.
            raw_log = self._best_effort_raw_log(code, language, mock)
            self.root.after(0, self._on_run_done, result, raw_log, elapsed, None)
        except Exception as e:  # noqa: BLE001
            elapsed = time.monotonic() - start
            self.root.after(0, self._on_run_done, None, "", elapsed, e)
        finally:
            runner.reset_invoker()

    @staticmethod
    def _best_effort_raw_log(code: str, language: str, mock: bool) -> str:
        """For the diff/raw-log tabs, we need the pre-filter log.

        In mock mode we can regenerate it deterministically from the same
        heuristic the mock invoker uses. In real mode the runner has already
        cleaned up the project dir, so we honestly don't have it without
        plumbing it through RunResult — which we deliberately don't, so the
        model and the UI see the same shape. So in real mode the Raw tab
        will be empty; document this.
        """
        if not mock:
            return ""
        from ui.mock_invoker import _pick_log_and_results

        log, _, _ = _pick_log_and_results(code)
        return log

    def _on_run_done(self, result, raw_log: str, elapsed: float,
                     error: Optional[BaseException]) -> None:
        self.run_button.configure(state=tk.NORMAL)
        if error is not None:
            self._set_status(f"error after {elapsed:.2f}s — {error}")
            messagebox.showerror("Run failed", repr(error))
            return

        self._filtered_cache = result.output
        # If we have a raw_log captured (mock mode), use it; else show "(raw
        # log not retained — see status bar)" in the raw tab.
        if raw_log:
            self._raw_log_cache = raw_log
            self._write_text(self.raw_text, raw_log)
            filtered_for_diff = filter_log(raw_log)
            self._write_diff(raw_log, filtered_for_diff)
        else:
            self._raw_log_cache = ""
            self._write_text(
                self.raw_text,
                "(raw log not retained in real-Docker mode — only the filtered "
                "output is exposed via RunResult, by design.)\n",
            )
            self._write_text(self.diff_text, "(diff unavailable: no raw log)\n")

        self._write_text(self.filtered_text, result.output)
        try:
            import tiktoken
            tokens = len(tiktoken.get_encoding(spec_constants.TOKEN_ENCODING).encode(result.output))
        except Exception:  # noqa: BLE001
            tokens = -1
        self._set_status(
            f"done — exit_status={result.exit_status}  "
            f"wall={elapsed:.2f}s  tokens={tokens}/{spec_constants.TOKEN_CAP}"
        )


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
