"""
Clean, modern desktop front-end for the case search tool, built with
customtkinter. Replaces the original script's raw input() prompts.

Layout:
  - Header
  - Search card: aliases, date range, bench, output file
  - Run / Stop controls + progress bar
  - Scrolling live log
  - Settings dialog (tesseract path, headless toggle) reachable from
    the gear icon in the header
"""

import os
import queue
import threading
import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
from datetime import datetime

import customtkinter as ctk

from config import BENCH_OPTIONS, DEFAULT_OUTPUT_FILENAME
from scraper.date_utils import parse_user_date
from scraper.search_engine import SearchEngine
from gui.settings import load_settings, save_settings

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

ACCENT = "#2F6FED"
BG = "#F5F6FA"
CARD = "#FFFFFF"
TEXT_MUTED = "#6B7280"
SUCCESS = "#1E9E5A"
DANGER = "#E14B4B"


class CaseSearchApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Karnataka Judiciary Case Search")
        self.geometry("980x720")
        self.minsize(860, 620)
        self.configure(fg_color=BG)

        self.settings = load_settings()
        self.log_queue = queue.Queue()
        self.worker_thread = None
        self.engine = None
        self.run_start_time = None

        self._build_header()
        self._build_body()
        self._poll_log_queue()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=72)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=24, pady=10)

        ctk.CTkLabel(
            title_box, text="Case Search",
            font=ctk.CTkFont(size=20, weight="bold"), text_color="#111827",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box, text="Karnataka Judiciary — judgment & case record lookup",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        ).pack(anchor="w")

        ctk.CTkButton(
            header, text="\u2699  Settings", width=110, height=34,
            fg_color="transparent", border_width=1, border_color="#D1D5DB",
            text_color="#374151", hover_color="#F3F4F6",
            command=self._open_settings,
        ).pack(side="right", padx=24)

    def _build_body(self):
        body = ctk.CTkFrame(self, fg_color=BG)
        body.pack(fill="both", expand=True, padx=24, pady=20)
        body.grid_columnconfigure(0, weight=5)
        body.grid_columnconfigure(1, weight=6)
        body.grid_rowconfigure(0, weight=1)

        self._build_form_card(body)
        self._build_log_card(body)

    def _build_form_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=22, pady=22)

        self._section_label(inner, "Entity aliases")
        ctk.CTkLabel(
            inner, text="One per line, or comma-separated",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(0, 6))
        self.aliases_box = ctk.CTkTextbox(inner, height=90, corner_radius=8,
                                           border_width=1, border_color="#E5E7EB")
        self.aliases_box.pack(fill="x", pady=(0, 16))

        date_row = ctk.CTkFrame(inner, fg_color="transparent")
        date_row.pack(fill="x", pady=(0, 16))
        date_row.grid_columnconfigure(0, weight=1)
        date_row.grid_columnconfigure(1, weight=1)

        start_box = ctk.CTkFrame(date_row, fg_color="transparent")
        start_box.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._section_label(start_box, "Start date")
        self.start_entry = ctk.CTkEntry(start_box, placeholder_text="DD-MM-YYYY",
                                         corner_radius=8, border_width=1, border_color="#E5E7EB")
        self.start_entry.pack(fill="x")

        end_box = ctk.CTkFrame(date_row, fg_color="transparent")
        end_box.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self._section_label(end_box, "End date")
        self.end_entry = ctk.CTkEntry(end_box, placeholder_text="DD-MM-YYYY",
                                       corner_radius=8, border_width=1, border_color="#E5E7EB")
        self.end_entry.pack(fill="x")

        self._section_label(inner, "Bench")
        self.bench_menu = ctk.CTkOptionMenu(
            inner, values=list(BENCH_OPTIONS.keys()),
            fg_color="#EEF2FF", button_color=ACCENT, button_hover_color="#2558C4",
            text_color="#111827", corner_radius=8,
        )
        self.bench_menu.set("Principal Bench")
        self.bench_menu.pack(fill="x", pady=(0, 16))

        self._section_label(inner, "Save results to")
        output_row = ctk.CTkFrame(inner, fg_color="transparent")
        output_row.pack(fill="x", pady=(0, 20))
        self.output_entry = ctk.CTkEntry(
            output_row, corner_radius=8, border_width=1, border_color="#E5E7EB",
        )
        self.output_entry.insert(
            0, os.path.join(self.settings.get("last_output_dir", ""), DEFAULT_OUTPUT_FILENAME)
        )
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            output_row, text="Browse", width=80, height=28,
            fg_color="transparent", border_width=1, border_color="#D1D5DB",
            text_color="#374151", hover_color="#F3F4F6",
            command=self._browse_output,
        ).pack(side="left")

        button_row = ctk.CTkFrame(inner, fg_color="transparent")
        button_row.pack(fill="x", pady=(4, 0))

        self.run_button = ctk.CTkButton(
            button_row, text="Run Search", height=40, corner_radius=8,
            fg_color=ACCENT, hover_color="#2558C4",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start_search,
        )
        self.run_button.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.stop_button = ctk.CTkButton(
            button_row, text="Stop", height=40, width=90, corner_radius=8,
            fg_color="#FEE2E2", hover_color="#FCA5A5", text_color=DANGER,
            state="disabled",
            command=self._stop_search,
        )
        self.stop_button.pack(side="left")

        self.progress_bar = ctk.CTkProgressBar(inner, corner_radius=6, progress_color=ACCENT)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(16, 4))

        self.status_label = ctk.CTkLabel(
            inner, text="Ready", font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        )
        self.status_label.pack(anchor="w")

    def _build_log_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14)
        card.grid(row=0, column=1, sticky="nsew", padx=(12, 0))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=22, pady=22)

        header_row = ctk.CTkFrame(inner, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            header_row, text="Activity log",
            font=ctk.CTkFont(size=15, weight="bold"), text_color="#111827",
        ).pack(side="left")
        ctk.CTkButton(
            header_row, text="Clear", width=64, height=26,
            fg_color="transparent", border_width=1, border_color="#D1D5DB",
            text_color="#374151", hover_color="#F3F4F6",
            command=self._clear_log,
        ).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            inner, corner_radius=8, fg_color="#0F172A", text_color="#E2E8F0",
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

    def _section_label(self, parent, text):
        ctk.CTkLabel(
            parent, text=text, font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#111827",
        ).pack(anchor="w", pady=(0, 4))

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def _open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("460x260")
        dialog.grab_set()

        pad = {"padx": 20, "pady": (16, 4)}
        ctk.CTkLabel(dialog, text="Tesseract OCR path", font=ctk.CTkFont(weight="bold")).pack(anchor="w", **pad)
        path_row = ctk.CTkFrame(dialog, fg_color="transparent")
        path_row.pack(fill="x", padx=20)
        path_entry = ctk.CTkEntry(path_row)
        path_entry.insert(0, self.settings.get("tesseract_path", ""))
        path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        def browse_tesseract():
            path = filedialog.askopenfilename(title="Locate tesseract executable")
            if path:
                path_entry.delete(0, "end")
                path_entry.insert(0, path)

        ctk.CTkButton(path_row, text="Browse", width=80, command=browse_tesseract).pack(side="left")

        headless_var = tk.BooleanVar(value=self.settings.get("headless", False))
        ctk.CTkCheckBox(
            dialog, text="Run browser headless (hidden window)",
            variable=headless_var,
        ).pack(anchor="w", padx=20, pady=(16, 4))

        ctk.CTkLabel(
            dialog,
            text="Headless mode is faster but you won't see the site while it runs.",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, wraplength=400, justify="left",
        ).pack(anchor="w", padx=20)

        def save_and_close():
            self.settings["tesseract_path"] = path_entry.get().strip()
            self.settings["headless"] = headless_var.get()
            save_settings(self.settings)
            dialog.destroy()

        ctk.CTkButton(
            dialog, text="Save", fg_color=ACCENT, hover_color="#2558C4",
            command=save_and_close,
        ).pack(pady=20)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
            initialfile=DEFAULT_OUTPUT_FILENAME,
        )
        if path:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, path)
            self.settings["last_output_dir"] = os.path.dirname(path)
            save_settings(self.settings)

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _append_log(self, message):
        self.log_box.configure(state="normal")
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{timestamp}] {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _parse_aliases(self):
        raw = self.aliases_box.get("1.0", "end").strip()
        if not raw:
            return []
        # Support both newline- and comma-separated input.
        parts = [p.strip() for chunk in raw.splitlines() for p in chunk.split(",")]
        return [p for p in parts if p]

    def _start_search(self):
        aliases = self._parse_aliases()
        if not aliases:
            messagebox.showwarning("Missing aliases", "Enter at least one entity alias.")
            return

        try:
            start_date = parse_user_date(self.start_entry.get())
            end_date = parse_user_date(self.end_entry.get())
        except ValueError:
            messagebox.showerror("Invalid date", "Dates must use DD-MM-YYYY format, e.g. 01-01-2025.")
            return

        if start_date > end_date:
            messagebox.showerror("Invalid range", "Start date must be on or before the end date.")
            return

        bench_name = self.bench_menu.get()
        bench_value = BENCH_OPTIONS[bench_name]
        output_path = self.output_entry.get().strip() or DEFAULT_OUTPUT_FILENAME

        self._clear_log()
        self.progress_bar.set(0)
        self.status_label.configure(text="Starting...", text_color=TEXT_MUTED)
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

        self.engine = SearchEngine(
            log=lambda msg: self.log_queue.put(("log", msg)),
            on_progress=lambda done, total: self.log_queue.put(("progress", (done, total))),
            tesseract_cmd=self.settings.get("tesseract_path") or None,
            headless=self.settings.get("headless", False),
        )

        def worker():
            try:
                summary = self.engine.run(aliases, start_date, end_date, bench_value, bench_name, output_path)
                self.log_queue.put(("done", summary))
            except Exception as e:
                self.log_queue.put(("error", str(e)))

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _stop_search(self):
        if self.engine:
            self.engine.request_stop()
            self.status_label.configure(text="Stopping after the current step...", text_color=DANGER)
            self.stop_button.configure(state="disabled")

    # ------------------------------------------------------------------
    # Background -> UI thread bridge
    # ------------------------------------------------------------------

    def _poll_log_queue(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()

                if kind == "log":
                    self._append_log(payload)

                elif kind == "progress":
                    done, total = payload
                    if total:
                        self.progress_bar.set(done / total)
                    self.status_label.configure(
                        text=f"Processed {done} of {total} search job(s)...", text_color=TEXT_MUTED,
                    )

                elif kind == "done":
                    self.progress_bar.set(1)
                    cancelled = payload.get("cancelled")
                    status = "Stopped" if cancelled else "Done"
                    self.status_label.configure(
                        text=(
                            f"{status} — {payload['case_count']} case(s) saved, "
                            f"{payload['duplicates_skipped']} duplicate(s) skipped."
                        ),
                        text_color=DANGER if cancelled else SUCCESS,
                    )
                    self._append_log(f"Output saved to {payload['output_path']}")
                    self.run_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")

                elif kind == "error":
                    self.status_label.configure(text="Error — see log", text_color=DANGER)
                    self._append_log(f"ERROR: {payload}")
                    self.run_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")

        except queue.Empty:
            pass

        self.after(150, self._poll_log_queue)


def launch():
    app = CaseSearchApp()
    app.mainloop()
