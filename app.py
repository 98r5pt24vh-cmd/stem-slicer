import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from stem_slicer_core import APP_NAME, process_audio


BG = "#1f1f1f"
PANEL = "#2f2f2f"
PANEL_HOVER = "#3a3a3a"
TEXT = "#e8e8e8"
MUTED = "#a8a8a8"
ACCENT = "#ff4f29"
BLUE = "#1e8bff"


class StemSlicerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1040x640")
        self.minsize(860, 560)
        self.configure(bg=BG)

        self.source_folder = tk.StringVar()
        self.output_folder = tk.StringVar()
        self.status_text = tk.StringVar(value="Ready.")
        self.progress_value = tk.DoubleVar(value=0)
        self.messages = queue.Queue()
        self.processing = False

        self._configure_style()
        self._build_ui()
        self.after(100, self._poll_messages)

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Stem.Horizontal.TProgressbar",
            troughcolor=PANEL,
            background=BLUE,
            bordercolor=PANEL,
            lightcolor=BLUE,
            darkcolor=BLUE,
            thickness=10,
        )

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        root = tk.Frame(self, bg=BG)
        root.grid(row=0, column=0, sticky="nsew")
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(0, weight=1)

        content = tk.Frame(root, bg=BG)
        content.grid(row=0, column=0, sticky="nsew", padx=54, pady=54)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=0)

        header = tk.Frame(content, bg=BG)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        tk.Label(
            header,
            text=APP_NAME,
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 34, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="Made with <3 by ANTIWORLD",
            bg=BG,
            fg=ACCENT,
            font=("Segoe UI", 20),
            anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=(32, 0))

        tk.Label(
            content,
            text="Split MP3 loops into clean layers.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 17, "bold"),
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(24, 58))

        self._folder_row(
            content,
            row=2,
            title="Source folder",
            subtitle="Choose the folder that contains your MP3 loops.",
            command=self._choose_source,
        )
        self._folder_row(
            content,
            row=3,
            title="Output folder",
            subtitle="Choose where generated layers should be saved.",
            command=self._choose_output,
        )

        spacer = tk.Frame(content, bg=BG, height=58)
        spacer.grid(row=4, column=0, columnspan=2, sticky="ew")

        self.progress = ttk.Progressbar(
            content,
            style="Stem.Horizontal.TProgressbar",
            mode="determinate",
            maximum=100,
            variable=self.progress_value,
        )
        self.progress.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 24))

        tk.Label(
            content,
            textvariable=self.status_text,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 14, "bold"),
            anchor="w",
        ).grid(row=6, column=0, columnspan=2, sticky="ew")

        content.grid_rowconfigure(7, weight=1)
        self.start_button = tk.Button(
            content,
            text="Start processing",
            command=self._start_processing,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL_HOVER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", 15, "bold"),
            height=2,
        )
        self.start_button.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(42, 0))

    def _folder_row(self, parent, row, title, subtitle, command):
        label_box = tk.Frame(parent, bg=BG)
        label_box.grid(row=row, column=0, sticky="ew", pady=(0, 58))
        label_box.grid_columnconfigure(0, weight=1)

        tk.Label(
            label_box,
            text=title,
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 16, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            label_box,
            text=subtitle,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 14, "bold"),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(18, 0))

        button = tk.Button(
            parent,
            text="Choose...",
            command=command,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL_HOVER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", 14, "bold"),
            width=14,
            height=1,
        )
        button.grid(row=row, column=1, sticky="e", pady=(0, 58), padx=(32, 0))

    def _choose_source(self):
        folder = filedialog.askdirectory(title="Choose source folder")
        if folder:
            self.source_folder.set(folder)
            self.status_text.set(f"Source: {folder}")

    def _choose_output(self):
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.output_folder.set(folder)
            self.status_text.set(f"Output: {folder}")

    def _start_processing(self):
        if self.processing:
            return
        self.processing = True
        self.progress_value.set(0)
        self.status_text.set("Starting...")
        self.start_button.configure(text="Processing...", state="disabled")

        worker = threading.Thread(
            target=self._run_processing,
            args=(self.source_folder.get(), self.output_folder.get()),
            daemon=True,
        )
        worker.start()

    def _run_processing(self, source, output):
        def on_progress(done, total, message):
            self.messages.put(("progress", done, total, message))

        def on_done():
            self.messages.put(("done",))

        def on_error(message):
            self.messages.put(("error", message))

        process_audio(source, output, on_progress, on_done, on_error)

    def _poll_messages(self):
        try:
            while True:
                item = self.messages.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _, done, total, message = item
                    pct = (done / total * 100) if total else 0
                    self.progress_value.set(pct)
                    self.status_text.set(message)
                elif kind == "done":
                    self.processing = False
                    self.progress_value.set(100)
                    self.status_text.set("Done.")
                    self.start_button.configure(text="Start processing", state="normal")
                    messagebox.showinfo(APP_NAME, "Processing complete.")
                elif kind == "error":
                    self.processing = False
                    self.start_button.configure(text="Start processing", state="normal")
                    self.status_text.set(item[1])
                    messagebox.showerror(APP_NAME, item[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_messages)


if __name__ == "__main__":
    StemSlicerApp().mainloop()
