"""Desktop launcher for the eyes processing toolbox."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


BASE_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Stage:
    label: str
    module: str
    extra_args: tuple[str, ...] = ()


PIPELINE: tuple[Stage, ...] = (
    Stage("Preprocess", "eyeslib.preprocess.pre_process"),
    Stage("Remove Consecutive Duplicates", "eyeslib.preprocess.uniq"),
    Stage("Reorder Identical-Timestamp Events", "eyeslib.preprocess.reorder"),
    Stage("Detect Gaps", "eyeslib.runners.run_gap_segments"),
    Stage("Detect Shutdown Segments", "eyeslib.runners.run_shutdown_segments"),
    Stage("Detect Idle Segments", "eyeslib.runners.run_idle_segments"),
    Stage("Build State Blocks", "eyeslib.runners.run_all_blocks"),
    Stage("Parse Activity Logs", "eyeslib.runners.run_parser4", ("Y",)),
    Stage("Build App-Level Usage", "eyeslib.runners.run_app_level"),
    Stage("Build Primary/Secondary Usage", "eyeslib.runners.run_secondary_nest"),
    Stage("Merge Activity With Blocks", "eyeslib.runners.run_merge_app_status"),
    Stage("Generate FAU Usage", "eyeslib.runners.run_fau_screen_time"),
    Stage("Plot Usage Graphs", "eyeslib.usage.visualize_app_usage"),
    Stage("Generate Pickups", "eyeslib.runners.run_all_pickups", ("5", "5")),
    Stage("Add Pickup Timezones", "eyeslib.runners.run_tz_columns_for_pickups"),
    Stage("Generate All Events", "eyeslib.runners.run_all_events"),
    Stage("Add Event Timezones", "eyeslib.runners.run_tz_columns_for_events"),
)


class EyesToolboxApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Eyes Toolbox")
        self.root.geometry("920x640")
        self.root.minsize(760, 520)

        self.folder_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Choose a folder with raw Chronicle CSV files.")
        self.stage_var = tk.StringVar(value="Ready")
        self.elapsed_var = tk.StringVar(value="Elapsed: 00:00")
        self.python_var = tk.StringVar(value=sys.executable)

        self.message_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.current_process: subprocess.Popen[str] | None = None
        self.stop_requested = False
        self.running = False
        self.run_started_at: float | None = None
        self.pending_session_reset = False

        self._build_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_queue)
        self.root.after(250, self._tick_timer)

    def _build_widgets(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill="both", expand=True)

        title = ttk.Label(container, text="Eyes Toolbox", font=("Helvetica", 18, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(
            container,
            text="Select a folder containing raw Chronicle CSV files, then run the full processing pipeline.",
        )
        subtitle.pack(anchor="w", pady=(4, 14))

        picker = ttk.Frame(container)
        picker.pack(fill="x")

        ttk.Label(picker, text="Raw CSV Folder").pack(anchor="w")
        picker_row = ttk.Frame(picker)
        picker_row.pack(fill="x", pady=(6, 0))

        self.folder_entry = ttk.Entry(picker_row, textvariable=self.folder_var)
        self.folder_entry.pack(side="left", fill="x", expand=True)

        self.browse_button = ttk.Button(picker_row, text="Browse...", command=self._browse)
        self.browse_button.pack(side="left", padx=(8, 0))

        meta = ttk.Frame(container)
        meta.pack(fill="x", pady=(12, 10))

        ttk.Label(meta, text="Python").grid(row=0, column=0, sticky="w")
        ttk.Label(meta, text="Timer").grid(row=0, column=1, sticky="w", padx=(12, 0))
        python_entry = ttk.Entry(meta, textvariable=self.python_var, state="readonly")
        python_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        timer_value = ttk.Label(meta, textvariable=self.elapsed_var, font=("Helvetica", 11, "bold"))
        timer_value.grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(4, 0))
        meta.columnconfigure(0, weight=1)

        stage_frame = ttk.LabelFrame(container, text="Pipeline Status", padding=12)
        stage_frame.pack(fill="x", pady=(4, 12))

        ttk.Label(stage_frame, textvariable=self.stage_var).pack(anchor="w")
        self.progress = ttk.Progressbar(
            stage_frame,
            mode="determinate",
            maximum=len(PIPELINE),
            value=0,
            style="Bright.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", pady=(10, 6))
        ttk.Label(stage_frame, textvariable=self.status_var).pack(anchor="w")

        buttons = ttk.Frame(container)
        buttons.pack(fill="x", pady=(0, 12))

        self.go_button = ttk.Button(buttons, text="Go", command=self._start)
        self.go_button.pack(side="left")

        self.stop_button = ttk.Button(buttons, text="Stop", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))

        self.end_session_button = ttk.Button(buttons, text="End Session", command=self._end_session)
        self.end_session_button.pack(side="left", padx=(8, 0))

        log_frame = ttk.LabelFrame(container, text="Run Log", padding=8)
        log_frame.pack(fill="both", expand=True)

        self.log = tk.Text(log_frame, wrap="word", height=20)
        self.log.pack(side="left", fill="both", expand=True)
        self.log.configure(state="disabled")

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)

    def _browse(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Select Raw Chronicle Folder",
            mustexist=True,
        )
        if selected:
            self.folder_var.set(selected)
        self.root.after(10, self._restore_focus_after_dialog)

    def _restore_focus_after_dialog(self) -> None:
        self._activate_window(self.folder_entry)

    def _activate_window(self, focus_target: tk.Misc | None = None) -> None:
        self.root.deiconify()
        self.root.update_idletasks()
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
            self.root.after_idle(lambda: self.root.attributes("-topmost", False))
        except tk.TclError:
            pass
        try:
            self.root.focus_force()
        except tk.TclError:
            self.root.focus_set()
        if focus_target is not None:
            try:
                focus_target.focus_set()
                return
            except tk.TclError:
                pass
        self.folder_entry.focus_set()

    def _start(self) -> None:
        if self.running:
            return

        folder = Path(self.folder_var.get()).expanduser()
        if not folder.exists() or not folder.is_dir():
            messagebox.showerror("Invalid Folder", "Please choose an existing folder.")
            return

        csv_files = list(folder.glob("*.csv"))
        if not csv_files:
            messagebox.showerror("No CSV Files", "The selected folder does not contain any CSV files.")
            return

        self._clear_log()
        self.progress.configure(value=0, maximum=len(PIPELINE))
        self.stage_var.set("Starting...")
        self.status_var.set(f"Found {len(csv_files)} raw CSV file(s).")
        self.elapsed_var.set("Elapsed: 00:00")
        self._append_log(f"Folder: {folder}\n")
        self._append_log(f"Python: {sys.executable}\n")
        self._append_log(f"Working directory: {BASE_DIR}\n")

        self.stop_requested = False
        self.pending_session_reset = False
        self.running = True
        self.run_started_at = time.monotonic()
        self.go_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.end_session_button.configure(state="normal")

        self.worker_thread = threading.Thread(target=self._run_pipeline, args=(folder,), daemon=True)
        self.worker_thread.start()

    def _stop(self) -> None:
        self.stop_requested = True
        self.status_var.set("Stopping after the current subprocess exits...")
        if self.current_process and self.current_process.poll() is None:
            self.current_process.terminate()

    def _end_session(self) -> None:
        if self.running:
            should_end = messagebox.askyesno(
                "End Session",
                "A pipeline run is still in progress. Do you want to stop it and reset this session?",
            )
            if not should_end:
                return

            self.pending_session_reset = True
            self.stop_requested = True
            self.status_var.set("Ending session...")
            if self.current_process and self.current_process.poll() is None:
                self.current_process.terminate()
            else:
                self._reset_session()
            return

        self._reset_session()

    def _run_pipeline(self, folder: Path) -> None:
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            for index, stage in enumerate(PIPELINE, start=1):
                if self.stop_requested:
                    self.message_queue.put(("done", False, "Pipeline stopped by user."))
                    return

                command = [sys.executable, "-m", stage.module, str(folder), *stage.extra_args]
                self.message_queue.put(("stage", index, stage.label))
                self.message_queue.put(("log", f"\n[{index}/{len(PIPELINE)}] {stage.label}\n"))
                self.message_queue.put(("log", f"$ {' '.join(shlex.quote(part) for part in command)}\n"))

                process = subprocess.Popen(
                    command,
                    cwd=BASE_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                )
                self.current_process = process

                assert process.stdout is not None
                for line in process.stdout:
                    self.message_queue.put(("log", line))
                    if self.stop_requested:
                        break

                return_code = process.wait()
                self.current_process = None

                if self.stop_requested:
                    self.message_queue.put(("done", False, "Pipeline stopped by user."))
                    return

                if return_code != 0:
                    self.message_queue.put(
                        ("done", False, f"Stage failed: {stage.label} (exit code {return_code}).")
                    )
                    return

            output_dir = folder / "processed"
            self.message_queue.put(("done", True, f"Pipeline finished. Outputs are in {output_dir}"))
        except Exception as exc:  # pragma: no cover - defensive GUI path
            self.current_process = None
            self.message_queue.put(("done", False, f"Pipeline failed: {exc}"))

    def _poll_queue(self) -> None:
        while True:
            try:
                item = self.message_queue.get_nowait()
            except queue.Empty:
                break

            kind = item[0]
            if kind == "log":
                self._append_log(item[1])
            elif kind == "stage":
                _, index, label = item
                self.progress.configure(value=index - 1)
                self.stage_var.set(f"Step {index}/{len(PIPELINE)}: {label}")
                self.status_var.set("Running...")
            elif kind == "done":
                _, success, message = item
                self.running = False
                self.current_process = None
                self.run_started_at = None
                self.go_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.end_session_button.configure(state="normal")
                self.progress.configure(value=len(PIPELINE) if success else self.progress["value"])
                self.stage_var.set("Completed" if success else "Stopped")
                self.status_var.set(str(message))
                self._append_log(f"\n{message}\n")
                if self.pending_session_reset:
                    self._reset_session()

        self.root.after(100, self._poll_queue)

    def _tick_timer(self) -> None:
        if self.running and self.run_started_at is not None:
            elapsed_seconds = int(time.monotonic() - self.run_started_at)
            hours, remainder = divmod(elapsed_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                self.elapsed_var.set(f"Elapsed: {hours:02d}:{minutes:02d}:{seconds:02d}")
            else:
                self.elapsed_var.set(f"Elapsed: {minutes:02d}:{seconds:02d}")
        self.root.after(250, self._tick_timer)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _reset_session(self) -> None:
        self.pending_session_reset = False
        self.stop_requested = False
        self.running = False
        self.current_process = None
        self.run_started_at = None
        self.folder_var.set("")
        self.stage_var.set("Ready")
        self.status_var.set("Choose a folder with raw Chronicle CSV files.")
        self.elapsed_var.set("Elapsed: 00:00")
        self.progress.configure(value=0, maximum=len(PIPELINE))
        self.go_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.end_session_button.configure(state="normal")
        self._clear_log()

    def _on_close(self) -> None:
        if self.running:
            should_close = messagebox.askyesno(
                "Quit Eyes Toolbox",
                "A pipeline run is still in progress. Do you want to stop it and close the window?",
            )
            if not should_close:
                return
            self._stop()

        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Bright.Horizontal.TProgressbar",
        troughcolor="#dce7ef",
        background="#12b5ff",
        bordercolor="#dce7ef",
        lightcolor="#52d0ff",
        darkcolor="#0a9be0",
        thickness=18,
    )
    EyesToolboxApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
