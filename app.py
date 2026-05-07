import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
import ctypes
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False


CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1260
OUTPUT_FPS = 25
APP_NAME = "基地边缘竖版视频合成器Pro"
APP_VERSION = "1.3"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}
IMAGE_EXTENSIONS = {".png"}
WINDOWS_FORBIDDEN_CHARS = r'\/:*?"<>|'
QUALITY_BITRATES = {
    "最佳 - 15 Mbps": "15M",
    "高 - 8 Mbps": "8M",
    "普通 - 6 Mbps": "6M",
}


def enable_dpi_awareness():
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_or_path(name: str) -> str | None:
    exe_name = f"{name}.exe" if os.name == "nt" else name
    local = app_dir() / exe_name
    if local.exists():
        return str(local)
    return shutil.which(name) or shutil.which(exe_name)


def startup_info():
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return info


def run_capture(args: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            startupinfo=startup_info(),
            encoding="utf-8",
            errors="replace",
        )
        return completed.returncode, completed.stdout
    except Exception as exc:
        return 1, str(exc)


def has_nvenc(ffmpeg_path: str) -> bool:
    code, output = run_capture([ffmpeg_path, "-hide_banner", "-encoders"], timeout=30)
    return code == 0 and "h264_nvenc" in output


def ffmpeg_version(ffmpeg_path: str) -> tuple[bool, str]:
    code, output = run_capture([ffmpeg_path, "-hide_banner", "-version"], timeout=30)
    first_line = output.strip().splitlines()[0] if output.strip() else ""
    return code == 0 and first_line.lower().startswith("ffmpeg version"), first_line or output.strip()


def probe_duration(ffprobe_path: str | None, video_path: str) -> float | None:
    if not ffprobe_path:
        return None
    code, output = run_capture(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        timeout=30,
    )
    if code != 0:
        return None
    try:
        duration = float(output.strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def seconds_from_ffmpeg_time(value: str) -> float | None:
    match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", value.strip())
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def quote_for_log(args: list[str]) -> str:
    return " ".join(f'"{arg}"' if " " in arg else arg for arg in args)


def clean_filename(name: str) -> str:
    cleaned = "".join("_" if char in WINDOWS_FORBIDDEN_CHARS else char for char in name).strip()
    return cleaned.rstrip(". ")


def normalize_version(value: str) -> str:
    text = value.strip()
    if not text:
        return "V1"
    if text.isdigit():
        return f"V{text}"
    match = re.fullmatch(r"[vV](\d+)", text)
    if match:
        return f"V{match.group(1)}"
    return text


def bitrate_buffer(bitrate: str) -> str:
    match = re.fullmatch(r"(\d+)M", bitrate)
    if not match:
        return bitrate
    return f"{int(match.group(1)) * 2}M"


class VerticalWrapperApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("920x720")
        self.root.minsize(760, 520)

        self.ffmpeg_path = bundled_or_path("ffmpeg")
        self.ffprobe_path = bundled_or_path("ffprobe")
        self.nvenc_available = False
        self.ffmpeg_ready = False
        self.is_running = False
        self.log_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.colors = {
            "bg": "#f6f6f7",
            "surface": "#ffffff",
            "surface_alt": "#fafafa",
            "line": "#e4e4e7",
            "line_hover": "#b8d7ff",
            "text": "#171717",
            "muted": "#6f7177",
            "subtle": "#8a8d94",
            "accent": "#2563eb",
            "accent_soft": "#eff6ff",
            "success": "#16a34a",
            "success_soft": "#ecfdf3",
        }
        self.font = self._choose_font()
        self.icon_font = self._choose_icon_font()
        self.drop_cards: dict[str, tk.Canvas] = {}

        self.video_var = tk.StringVar()
        self.cover_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=str(Path.cwd()))

        self.naming_mode_var = tk.StringVar(value="template")
        self.project_type_var = tk.StringVar(value="商单")
        self.project_name_var = tk.StringVar(value="")
        self.version_var = tk.StringVar(value="V1")
        self.custom_name_var = tk.StringVar(value="")
        self.output_preview_var = tk.StringVar(value="")

        self.quality_var = tk.StringVar(value="高 - 8 Mbps")
        self.encoder_var = tk.StringVar(value="自动")
        self.encoder_hint_var = tk.StringVar(value="正在检测编码器...")
        self.y_offset_var = tk.StringVar(value="422")
        self.cq_var = tk.StringVar(value="18")
        self.preset_var = tk.StringVar(value="p5")
        self.advanced_visible = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="准备就绪")

        self._build_ui()
        self._install_drag_drop()
        self._wire_preview_updates()
        self._update_naming_state()
        self._update_output_preview()
        self._update_encoder_hint()
        self._detect_ffmpeg_async()
        self._poll_queue()

    def _build_ui(self):
        self._setup_style()
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root.configure(bg=self.colors["bg"])

        notebook = ttk.Notebook(self.root, style="Clean.TNotebook")
        notebook.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)

        work_tab = ttk.Frame(notebook, padding=0, style="App.TFrame")
        log_tab = ttk.Frame(notebook, padding=12, style="App.TFrame")
        notebook.add(work_tab, text="操作")
        notebook.add(log_tab, text="日志")

        work_tab.columnconfigure(0, weight=1)
        work_tab.rowconfigure(1, weight=1)

        header = ttk.Frame(work_tab, padding=(20, 18, 20, 10), style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=1, sticky="e")
        ttk.Label(header, text=f"v{APP_VERSION}", style="Version.TLabel").grid(row=1, column=1, sticky="e", pady=(6, 0))
        ttk.Label(header, text="拖入横屏视频和封套图，输出固定规格的竖版 MP4。", style="HeroSub.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        scroll_shell = ttk.Frame(work_tab, style="App.TFrame")
        scroll_shell.grid(row=1, column=0, sticky="nsew")
        scroll_shell.columnconfigure(0, weight=1)
        scroll_shell.rowconfigure(0, weight=1)

        self.body_canvas = tk.Canvas(scroll_shell, bg=self.colors["bg"], highlightthickness=0)
        body_scrollbar = ttk.Scrollbar(scroll_shell, orient="vertical", command=self.body_canvas.yview)
        self.body = ttk.Frame(self.body_canvas, padding=(20, 2, 20, 16), style="App.TFrame")
        self.body_window = self.body_canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body_canvas.configure(yscrollcommand=body_scrollbar.set)
        self.body_canvas.grid(row=0, column=0, sticky="nsew")
        body_scrollbar.grid(row=0, column=1, sticky="ns")
        self.body_canvas.bind("<Configure>", self._resize_body_window)
        self.body.bind("<Configure>", lambda _event: self.body_canvas.configure(scrollregion=self.body_canvas.bbox("all")))
        self.body_canvas.bind("<Enter>", self._bind_mousewheel)
        self.body_canvas.bind("<Leave>", self._unbind_mousewheel)

        self.body.columnconfigure(0, weight=1)
        self._build_body(self.body)

        footer = ttk.Frame(work_tab, padding=(20, 12, 20, 18), style="Footer.TFrame")
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)
        self.start_button = ttk.Button(footer, text="开始生成", command=self.start, style="Accent.TButton")
        self.start_button.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, orient="horizontal", mode="determinate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=(14, 0))

        self._build_log_tab(log_tab)

    def _build_body(self, parent: ttk.Frame):
        file_area = ttk.Frame(parent, style="App.TFrame")
        file_area.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        file_area.columnconfigure(0, weight=1, uniform="drop")
        file_area.columnconfigure(1, weight=1, uniform="drop")

        self.video_drop = self._drop_card(
            file_area,
            0,
            0,
            "横屏视频",
            "MP4 / MOV / MKV",
            self.video_var,
            "video",
            self.choose_video,
        )
        self.cover_drop = self._drop_card(
            file_area,
            0,
            1,
            "封套 PNG",
            "1080 x 1260 PNG",
            self.cover_var,
            "cover",
            self.choose_cover,
        )

        output_box = ttk.Frame(parent, padding=14, style="Card.TFrame")
        output_box.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        output_box.columnconfigure(1, weight=1)
        self.output_entry = self._path_row(output_box, 0, "输出目录", self.output_dir_var, self.choose_output_dir)

        drag_text = "支持拖拽到对应区域" if DND_AVAILABLE else "拖拽组件未启用；可用按钮选择文件"
        ttk.Label(parent, text=drag_text, style="PageHint.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 12))

        _, naming = self._section_card(parent, 3, "输出命名")
        naming.columnconfigure(0, weight=1)
        self._build_naming_section(naming)

        _, export = self._section_card(parent, 4, "导出设置")
        export.columnconfigure(0, weight=1)
        export.columnconfigure(1, weight=1)
        self._build_export_section(export)

        self.advanced_section, self.advanced_frame = self._section_card(parent, 5, "高级参数")
        self.advanced_section.grid_remove()
        self.advanced_frame.columnconfigure(1, weight=1)
        self._advanced_row(0, "视频顶部 Y", self.y_offset_var)
        self._advanced_row(1, "NVENC CQ", self.cq_var)
        self._advanced_row(2, "输出 preset", self.preset_var)

    def _build_naming_section(self, parent: ttk.Frame):
        mode_row = ttk.Frame(parent, style="Card.TFrame")
        mode_row.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Radiobutton(
            mode_row,
            text="模板",
            value="template",
            variable=self.naming_mode_var,
            command=self._update_naming_state,
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Radiobutton(
            mode_row,
            text="自定义",
            value="custom",
            variable=self.naming_mode_var,
            command=self._update_naming_state,
        ).grid(row=0, column=1, sticky="w")

        template_grid = ttk.Frame(parent, style="Card.TFrame")
        template_grid.grid(row=1, column=0, sticky="ew")
        template_grid.columnconfigure(1, weight=1)

        ttk.Label(template_grid, text="类型", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(template_grid, text="项目名称", style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(template_grid, text="版本号", style="Muted.TLabel").grid(row=0, column=2, sticky="w", padx=(10, 0))

        self.project_type_combo = ttk.Combobox(
            template_grid,
            textvariable=self.project_type_var,
            values=["商单", "基地"],
            state="readonly",
            width=9,
        )
        self.project_type_combo.grid(row=1, column=0, sticky="w", pady=(5, 0))

        self.project_name_entry = ttk.Entry(template_grid, textvariable=self.project_name_var, width=28)
        self.project_name_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(5, 0), ipady=4)

        self.version_combo = ttk.Combobox(
            template_grid,
            textvariable=self.version_var,
            values=[f"V{i}" for i in range(1, 21)],
            width=10,
        )
        self.version_combo.grid(row=1, column=2, sticky="w", padx=(10, 0), pady=(5, 0))

        custom_row = ttk.Frame(parent, style="Card.TFrame")
        custom_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        custom_row.columnconfigure(0, weight=1)
        ttk.Label(custom_row, text="自定义文件名", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.custom_name_entry = ttk.Entry(custom_row, textvariable=self.custom_name_var)
        self.custom_name_entry.grid(row=1, column=0, sticky="ew", pady=(5, 0), ipady=4)

        preview = ttk.Frame(parent, padding=(10, 8), style="PreviewBox.TFrame")
        preview.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        preview.columnconfigure(1, weight=1)
        ttk.Label(preview, text="预览", style="PreviewCaption.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(preview, textvariable=self.output_preview_var, style="Preview.TLabel").grid(
            row=0, column=1, sticky="ew", padx=(12, 0)
        )

    def _build_export_section(self, parent: ttk.Frame):
        quality_group = ttk.Frame(parent, style="Card.TFrame")
        quality_group.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        quality_group.columnconfigure(0, weight=1)
        ttk.Label(quality_group, text="导出质量", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.quality_combo = ttk.Combobox(
            quality_group,
            textvariable=self.quality_var,
            values=list(QUALITY_BITRATES.keys()),
            state="readonly",
        )
        self.quality_combo.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        encoder_group = ttk.Frame(parent, style="Card.TFrame")
        encoder_group.grid(row=0, column=1, sticky="ew")
        encoder_group.columnconfigure(0, weight=1)
        ttk.Label(encoder_group, text="编码方式", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.encoder_combo = ttk.Combobox(
            encoder_group,
            textvariable=self.encoder_var,
            values=["自动", "NVIDIA NVENC", "CPU x264"],
            state="readonly",
        )
        self.encoder_combo.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        hint_box = ttk.Frame(parent, padding=(10, 8), style="HintBox.TFrame")
        hint_box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        hint_box.columnconfigure(0, weight=1)
        ttk.Label(hint_box, textvariable=self.encoder_hint_var, style="InlineHint.TLabel", wraplength=520).grid(
            row=0, column=0, sticky="w"
        )

        advanced_toggle = ttk.Checkbutton(
            parent,
            text="显示高级参数",
            variable=self.advanced_visible,
            command=self._toggle_advanced,
        )
        advanced_toggle.grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _build_log_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            parent,
            height=18,
            wrap="word",
            state="disabled",
            relief="flat",
            bg=self.colors["surface"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            padx=14,
            pady=14,
            font=("Consolas", 10),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _section_card(self, parent: ttk.Frame, row: int, title: str):
        section = ttk.Frame(parent, style="App.TFrame")
        section.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        section.columnconfigure(0, weight=1)
        ttk.Label(section, text=title, style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 7))
        card = ttk.Frame(section, padding=14, style="Card.TFrame")
        card.grid(row=1, column=0, sticky="ew")
        return section, card

    def _setup_style(self):
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        self.root.option_add("*Font", (self.font, 10))
        style.configure(".", font=(self.font, 10))
        style.configure("App.TFrame", background=self.colors["bg"])
        style.configure("Footer.TFrame", background=self.colors["bg"])
        style.configure("Card.TFrame", background=self.colors["surface"], relief="flat")
        style.configure("PreviewBox.TFrame", background=self.colors["surface_alt"], relief="flat")
        style.configure("Title.TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=(self.font, 19, "bold"))
        style.configure("SectionTitle.TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=(self.font, 11, "bold"))
        style.configure("HeroSub.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=(self.font, 9))
        style.configure("PageHint.TLabel", background=self.colors["bg"], foreground=self.colors["subtle"], font=(self.font, 9))
        style.configure("Muted.TLabel", background=self.colors["surface"], foreground=self.colors["muted"], font=(self.font, 9))
        style.configure("InlineHint.TLabel", background=self.colors["accent_soft"], foreground=self.colors["accent"], font=(self.font, 9, "bold"))
        style.configure("Status.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=(self.font, 9))
        style.configure("Version.TLabel", background=self.colors["bg"], foreground=self.colors["subtle"], font=(self.font, 9, "bold"))
        style.configure("HintBox.TFrame", background=self.colors["accent_soft"], relief="flat")
        style.configure("PreviewCaption.TLabel", background=self.colors["surface_alt"], foreground=self.colors["muted"], font=(self.font, 9))
        style.configure("Preview.TLabel", background=self.colors["surface_alt"], foreground=self.colors["text"], font=(self.font, 10, "bold"))
        style.configure("DialogTitle.TLabel", background=self.colors["surface"], foreground=self.colors["text"], font=(self.font, 14, "bold"))
        style.configure("DialogFile.TLabel", background=self.colors["surface"], foreground=self.colors["muted"], font=(self.font, 9))
        style.configure("Accent.TButton", font=(self.font, 10, "bold"), padding=(20, 9))

    def _choose_font(self) -> str:
        available = set(tkfont.families(self.root))
        for candidate in ("MiSans", "MiSans VF", "MiSans Latin", "HarmonyOS Sans SC", "Microsoft YaHei UI", "Segoe UI"):
            if candidate in available:
                return candidate
        return "TkDefaultFont"

    def _choose_icon_font(self) -> str:
        available = set(tkfont.families(self.root))
        for candidate in ("Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI Symbol", self.font):
            if candidate in available:
                return candidate
        return self.font

    def _resize_body_window(self, event):
        self.body_canvas.itemconfigure(self.body_window, width=event.width)

    def _bind_mousewheel(self, _event):
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event):
        self.root.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self.body_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _path_row(self, parent, row: int, label: str, variable: tk.StringVar, command):
        ttk.Label(parent, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=5)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", padx=(10, 8), pady=5, ipady=4)
        ttk.Button(parent, text="选择", command=command).grid(row=row, column=2, sticky="e", pady=5)
        return entry

    def _advanced_row(self, row: int, label: str, variable: tk.StringVar):
        ttk.Label(self.advanced_frame, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(self.advanced_frame, textvariable=variable, width=18).grid(
            row=row, column=1, sticky="w", padx=(10, 0), pady=5, ipady=4
        )

    def _toggle_advanced(self):
        if self.advanced_visible.get():
            self.advanced_section.grid()
        else:
            self.advanced_section.grid_remove()
        self.body_canvas.after_idle(lambda: self.body_canvas.configure(scrollregion=self.body_canvas.bbox("all")))

    def _drop_card(self, parent, row: int, column: int, title: str, subtitle: str, variable: tk.StringVar, kind: str, command):
        canvas = tk.Canvas(
            parent,
            height=154,
            bg=self.colors["bg"],
            highlightthickness=0,
            cursor="hand2",
        )
        canvas.grid(row=row, column=column, sticky="ew", padx=(0, 8) if column == 0 else (8, 0))
        canvas.bind("<Configure>", lambda _event, c=canvas, t=title, s=subtitle, v=variable, k=kind: self._redraw_drop_card(c, t, s, v, k))
        canvas.bind("<Button-1>", lambda _event: command())
        canvas.bind("<Enter>", lambda _event, c=canvas, t=title, s=subtitle, v=variable, k=kind: self._redraw_drop_card(c, t, s, v, k, True))
        canvas.bind("<Leave>", lambda _event, c=canvas, t=title, s=subtitle, v=variable, k=kind: self._redraw_drop_card(c, t, s, v, k, False))
        variable.trace_add("write", lambda *_args, c=canvas, t=title, s=subtitle, v=variable, k=kind: self._redraw_drop_card(c, t, s, v, k))
        self.drop_cards[kind] = canvas
        return canvas

    def _redraw_drop_card(self, canvas: tk.Canvas, title: str, subtitle: str, variable: tk.StringVar, kind: str, hovered: bool = False):
        canvas.delete("all")
        width = max(canvas.winfo_width(), 260)
        height = max(canvas.winfo_height(), 140)
        selected = bool(variable.get())
        border = self.colors["success"] if selected else (self.colors["line_hover"] if hovered else self.colors["line"])
        fill = self.colors["success_soft"] if selected else (self.colors["accent_soft"] if hovered else self.colors["surface"])
        accent = self.colors["success"] if selected else self.colors["accent"]

        self._rounded_dash(canvas, 2, 2, width - 2, height - 2, 8, fill, border, selected)
        cx = width / 2
        icon_y = 44
        if kind == "video":
            self._draw_video_icon(canvas, cx, icon_y, accent)
        else:
            self._draw_image_icon(canvas, cx, icon_y, accent)

        if selected:
            self._draw_check(canvas, width - 28, 26)

        filename = self._display_name(variable.get())
        canvas.create_text(cx, 84, text=title, fill=self.colors["text"], font=(self.font, 12, "bold"))
        canvas.create_text(
            cx,
            109,
            text=filename or subtitle,
            fill=self.colors["text"] if selected else self.colors["muted"],
            font=(self.font, 9),
            width=width - 48,
        )
        canvas.create_text(
            cx,
            133,
            text="已选择" if selected else "点击选择 / 拖入文件",
            fill=accent,
            font=(self.font, 9, "bold" if selected else "normal"),
        )

    def _display_name(self, value: str) -> str:
        if not value:
            return ""
        name = Path(value).name
        return name if len(name) <= 36 else f"{name[:16]}...{name[-16:]}"

    def _rounded_dash(self, canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, radius: int, fill: str, outline: str, solid: bool = False):
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        canvas.create_polygon(points, smooth=True, fill=fill, outline="")
        dash = None if solid else (6, 5)
        canvas.create_line(points + points[:2], smooth=True, fill=outline, width=1.7, dash=dash)

    def _draw_video_icon(self, canvas: tk.Canvas, cx: float, cy: float, color: str):
        glyph = "\ue714" if self.icon_font in {"Segoe Fluent Icons", "Segoe MDL2 Assets"} else "▶"
        canvas.create_text(cx, cy, text=glyph, fill=color, font=(self.icon_font, 34))

    def _draw_image_icon(self, canvas: tk.Canvas, cx: float, cy: float, color: str):
        glyph = "\ue91b" if self.icon_font in {"Segoe Fluent Icons", "Segoe MDL2 Assets"} else "▧"
        canvas.create_text(cx, cy, text=glyph, fill=color, font=(self.icon_font, 34))

    def _draw_check(self, canvas: tk.Canvas, cx: float, cy: float):
        canvas.create_oval(cx - 12, cy - 12, cx + 12, cy + 12, fill=self.colors["success"], outline="")
        canvas.create_line(cx - 6, cy, cx - 1, cy + 5, cx + 7, cy - 6, fill="#ffffff", width=2.4, capstyle="round", joinstyle="round")

    def _wire_preview_updates(self):
        watched = [
            self.naming_mode_var,
            self.project_type_var,
            self.project_name_var,
            self.version_var,
            self.custom_name_var,
            self.output_dir_var,
            self.encoder_var,
        ]
        for var in watched:
            var.trace_add("write", lambda *_: self._on_ui_state_change())

    def _on_ui_state_change(self):
        self._update_output_preview()
        self._update_encoder_hint()

    def _update_naming_state(self):
        is_template = self.naming_mode_var.get() == "template"
        template_combo_state = "readonly" if is_template else "disabled"
        template_entry_state = "normal" if is_template else "disabled"
        custom_state = "normal" if not is_template else "disabled"

        self.project_type_combo.configure(state=template_combo_state)
        self.project_name_entry.configure(state=template_entry_state)
        self.version_combo.configure(state=template_entry_state)
        self.custom_name_entry.configure(state=custom_state)
        self._update_output_preview()

    def _update_encoder_hint(self):
        selected = self.encoder_var.get()
        if selected == "自动":
            if not self.ffmpeg_ready:
                text = "自动：等待检测编码器"
            elif self.nvenc_available:
                text = "自动预计使用 GPU / NVENC"
            else:
                text = "自动预计使用 CPU x264"
        elif selected == "NVIDIA NVENC":
            text = "已选择 GPU / NVENC"
        else:
            text = "已选择 CPU x264"
        self.encoder_hint_var.set(text)

    def _install_drag_drop(self):
        if not DND_AVAILABLE:
            return
        self.video_drop.drop_target_register(DND_FILES)
        self.video_drop.dnd_bind("<<Drop>>", lambda event: self._on_drop(event, "video"))
        self.cover_drop.drop_target_register(DND_FILES)
        self.cover_drop.dnd_bind("<<Drop>>", lambda event: self._on_drop(event, "cover"))
        self.output_entry.drop_target_register(DND_FILES)
        self.output_entry.dnd_bind("<<Drop>>", lambda event: self._on_drop(event, "output"))
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind("<<Drop>>", lambda event: self._on_drop(event, "auto"))

    def _on_drop(self, event, target: str):
        paths = self.root.tk.splitlist(event.data)
        if not paths:
            return
        path = paths[0]
        item = Path(path)
        suffix = item.suffix.lower()

        if target == "video":
            if suffix in VIDEO_EXTENSIONS:
                self.video_var.set(path)
            else:
                self._log(f"拖入的不是视频文件：{path}\n")
            return

        if target == "cover":
            if suffix in IMAGE_EXTENSIONS:
                self.cover_var.set(path)
            else:
                self._log(f"拖入的不是 PNG 文件：{path}\n")
            return

        if target == "output":
            if item.is_dir():
                self.output_dir_var.set(path)
            elif item.exists():
                self.output_dir_var.set(str(item.parent))
            else:
                self._log(f"输出目录不存在：{path}\n")
            return

        if suffix in VIDEO_EXTENSIONS:
            self.video_var.set(path)
        elif suffix in IMAGE_EXTENSIONS:
            self.cover_var.set(path)
        elif item.is_dir():
            self.output_dir_var.set(path)
        else:
            self._log(f"无法识别拖入文件类型：{path}\n")

    def choose_video(self):
        path = filedialog.askopenfilename(
            title="选择横屏视频",
            filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi *.m4v"), ("All files", "*.*")],
        )
        if path:
            self.video_var.set(path)

    def choose_cover(self):
        path = filedialog.askopenfilename(title="选择封套 PNG", filetypes=[("PNG files", "*.png"), ("All files", "*.*")])
        if path:
            self.cover_var.set(path)

    def choose_output_dir(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir_var.set(path)

    def _detect_ffmpeg_async(self):
        def worker():
            if not self.ffmpeg_path:
                self.log_queue.put(("status", "未找到 FFmpeg"))
                self.log_queue.put(("log", "未找到 FFmpeg。请把 ffmpeg.exe 放到程序同目录，或加入系统 PATH。\n"))
                self.log_queue.put(("encoder_hint", None))
                return
            self.log_queue.put(("log", f"FFmpeg：{self.ffmpeg_path}\n"))
            ready, version_text = ffmpeg_version(self.ffmpeg_path)
            if not ready:
                self.ffmpeg_ready = False
                self.log_queue.put(("status", "FFmpeg 不可运行"))
                detail = f"检测输出：{version_text}\n" if version_text else "检测命令没有返回任何版本信息。\n"
                self.log_queue.put(
                    (
                        "log",
                        "当前 ffmpeg.exe 不可运行或不是完整 FFmpeg。\n"
                        + detail
                        + "请换用完整 Windows 版 FFmpeg，并确保 ffprobe.exe 也在同一目录。\n",
                    )
                )
                self.log_queue.put(("encoder_hint", None))
                return
            self.ffmpeg_ready = True
            self.log_queue.put(("log", f"{version_text}\n"))
            self.nvenc_available = has_nvenc(self.ffmpeg_path)
            if self.nvenc_available:
                self.log_queue.put(("log", "已检测到 h264_nvenc，自动模式将优先使用 NVIDIA GPU 编码。\n"))
                self.log_queue.put(("status", "准备就绪：NVENC 可用"))
            else:
                self.log_queue.put(("log", "当前 FFmpeg 不支持 h264_nvenc，自动模式会使用 CPU x264 编码。\n"))
                self.log_queue.put(("status", "准备就绪：CPU 编码"))
            self.log_queue.put(("encoder_hint", None))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "encoder_hint":
                    self._update_encoder_hint()
                elif kind == "progress":
                    self._set_progress(float(payload))
                elif kind == "done":
                    self._on_done(str(payload))
                elif kind == "error":
                    self._on_error(str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_progress(self, value: float):
        if self.progress["mode"] != "determinate":
            self.progress.stop()
            self.progress.configure(mode="determinate")
        self.progress["value"] = max(0, min(100, value))

    def _filename_from_ui(self) -> str:
        if self.naming_mode_var.get() == "template":
            project_type = self.project_type_var.get().strip() or "商单"
            project_name = clean_filename(self.project_name_var.get())
            version = clean_filename(normalize_version(self.version_var.get()))
            filename = f"【竖版】{project_type}_{project_name}{version}.mp4"
        else:
            filename = clean_filename(self.custom_name_var.get())
            if filename.lower().endswith(".mp4"):
                filename = filename[:-4]
            filename = f"{filename}.mp4" if filename else ""
        return filename

    def _output_path_from_ui(self) -> str:
        return str(Path(self.output_dir_var.get()) / self._filename_from_ui())

    def _update_output_preview(self):
        filename = self._filename_from_ui()
        if filename:
            self.output_preview_var.set(filename)
        else:
            self.output_preview_var.set("请输入输出文件名")

    def _selected_bitrate(self) -> str:
        return QUALITY_BITRATES.get(self.quality_var.get(), "8M")

    def start(self):
        if self.is_running:
            return

        error = self._validate_inputs()
        if error:
            messagebox.showerror("无法开始", error, parent=self.root)
            return

        self.is_running = True
        self.start_button.configure(state="disabled")
        self.progress.configure(mode="determinate", value=0)
        self.status_var.set("生成中...")
        self._log("\n开始生成...\n")
        threading.Thread(target=self._run_job, daemon=True).start()

    def _validate_inputs(self) -> str | None:
        if not self.video_var.get().strip():
            return "请先选择横屏视频。"
        if not self.cover_var.get().strip():
            return "请先选择封套 PNG。"
        if not self.output_dir_var.get().strip():
            return "请先选择输出目录。"
        if not self._filename_from_ui():
            return "请填写输出文件名。"
        if self.naming_mode_var.get() == "template" and not self.project_name_var.get().strip():
            return "请填写项目名称。"
        if not self.ffmpeg_path:
            return "未找到 FFmpeg。请把 ffmpeg.exe 放到程序同目录，或加入系统 PATH。"
        if not self.ffmpeg_ready:
            return "当前 ffmpeg.exe 不可运行或不是完整 FFmpeg。请先更换完整 FFmpeg。"
        if not Path(self.video_var.get()).exists():
            return "输入视频文件不存在。"
        if not Path(self.cover_var.get()).exists():
            return "封套 PNG 文件不存在。"
        output_dir = Path(self.output_dir_var.get())
        if not output_dir.exists():
            return "输出目录不存在。"
        try:
            with tempfile.NamedTemporaryFile(prefix="vw_write_test_", dir=output_dir, delete=True):
                pass
        except Exception as exc:
            return f"输出目录不可写：{exc}"
        try:
            int(self.y_offset_var.get())
        except ValueError:
            return "视频顶部 Y 必须是整数。"
        try:
            number = int(self.cq_var.get())
        except ValueError:
            return "NVENC CQ 必须是整数。"
        if not 0 <= number <= 51:
            return "NVENC CQ 建议设置在 0 到 51 之间。"
        return None

    def _run_job(self):
        video = self.video_var.get()
        cover = self.cover_var.get()
        output = self._output_path_from_ui()
        duration = probe_duration(self.ffprobe_path, video)

        if duration is None:
            self.log_queue.put(("log", "未能读取视频时长，进度条将按未知时长显示。\n"))
            self.log_queue.put(("progress", 5))

        selected_encoder = self.encoder_var.get()
        use_nvenc = selected_encoder == "NVIDIA NVENC" or (selected_encoder == "自动" and self.nvenc_available)
        if selected_encoder == "自动" and not self.nvenc_available:
            self.log_queue.put(("log", "当前 FFmpeg 不支持 NVENC，已自动使用 CPU 编码。\n"))

        success = self._run_ffmpeg(video, cover, output, use_nvenc, duration)
        if not success and selected_encoder == "自动" and use_nvenc:
            self.log_queue.put(("log", "\nNVENC 输出失败，自动回退 CPU x264 再试一次。\n"))
            try:
                Path(output).unlink(missing_ok=True)
            except Exception:
                pass
            self.log_queue.put(("progress", 0))
            success = self._run_ffmpeg(video, cover, output, False, duration)

        if success:
            self.log_queue.put(("progress", 100))
            self.log_queue.put(("done", output))
        else:
            self.log_queue.put(("error", "输出失败。请查看“日志”标签页里的 FFmpeg 错误信息。"))

    def _build_ffmpeg_command(self, video: str, cover: str, output: str, use_nvenc: bool) -> list[str]:
        y_offset = int(self.y_offset_var.get())
        bitrate = self._selected_bitrate()
        bufsize = bitrate_buffer(bitrate)
        filter_complex = (
            f"[0:v]scale={CANVAS_WIDTH}:{CANVAS_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={CANVAS_WIDTH}:{CANVAS_HEIGHT},setsar=1[bg];"
            f"[1:v]scale={CANVAS_WIDTH}:-2,setsar=1[v];"
            f"[bg][v]overlay=0:{y_offset}:shortest=1,format=yuv420p[outv]"
        )
        command = [
            self.ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loop",
            "1",
            "-i",
            cover,
            "-i",
            video,
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-map",
            "1:a?",
            "-r",
            str(OUTPUT_FPS),
        ]
        if use_nvenc:
            preset = self.preset_var.get().strip() or "p5"
            command.extend(
                [
                    "-c:v",
                    "h264_nvenc",
                    "-preset",
                    preset,
                    "-rc",
                    "vbr",
                    "-cq",
                    self.cq_var.get(),
                    "-b:v",
                    bitrate,
                    "-maxrate",
                    bitrate,
                    "-bufsize",
                    bufsize,
                ]
            )
        else:
            preset = self.preset_var.get().strip()
            if not preset or preset.startswith("p"):
                preset = "medium"
            command.extend(
                [
                    "-c:v",
                    "libx264",
                    "-b:v",
                    bitrate,
                    "-maxrate",
                    bitrate,
                    "-bufsize",
                    bufsize,
                    "-preset",
                    preset,
                ]
            )

        command.extend(
            [
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                "-shortest",
                output,
            ]
        )
        return command

    def _run_ffmpeg(self, video: str, cover: str, output: str, use_nvenc: bool, duration: float | None) -> bool:
        encoder_name = "NVIDIA NVENC" if use_nvenc else "CPU x264"
        self.log_queue.put(("log", f"编码方式：{encoder_name}\n"))
        self.log_queue.put(("log", f"导出质量：{self.quality_var.get()} ({self._selected_bitrate()})\n"))
        self.log_queue.put(("log", f"输出文件：{output}\n"))
        command = self._build_ffmpeg_command(video, cover, output, use_nvenc)
        self.log_queue.put(("log", quote_for_log(command) + "\n\n"))

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startup_info(),
            )
        except Exception as exc:
            self.log_queue.put(("log", f"启动 FFmpeg 失败：{exc}\n"))
            return False

        assert process.stdout is not None
        for line in process.stdout:
            self.log_queue.put(("log", line))
            if duration:
                match = re.search(r"time=(\d+:\d+:\d+(?:\.\d+)?)", line)
                if match:
                    current = seconds_from_ffmpeg_time(match.group(1))
                    if current is not None:
                        self.log_queue.put(("progress", (current / duration) * 100))

        return process.wait() == 0 and Path(output).exists()

    def _on_done(self, output: str):
        self.is_running = False
        self.start_button.configure(state="normal")
        self.status_var.set(f"完成：{output}")
        self._log(f"\n生成完成：{output}\n")
        self._show_done_dialog(output)

    def _on_error(self, message: str):
        self.is_running = False
        self.start_button.configure(state="normal")
        self.status_var.set("生成失败")
        self._log(f"\n{message}\n")
        messagebox.showerror("生成失败", message, parent=self.root)

    def _show_done_dialog(self, output: str):
        dialog = tk.Toplevel(self.root)
        dialog.title("生成完成")
        dialog.configure(bg=self.colors["surface"])
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        box = ttk.Frame(dialog, padding=22, style="Card.TFrame")
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(1, weight=1)

        icon = tk.Canvas(box, width=42, height=42, bg=self.colors["surface"], highlightthickness=0)
        icon.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 14))
        icon.create_oval(4, 4, 38, 38, fill=self.colors["success"], outline="")
        icon.create_line(14, 22, 20, 28, 30, 15, fill="#ffffff", width=3, capstyle="round", joinstyle="round")

        ttk.Label(box, text="竖版视频已生成", style="DialogTitle.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(box, text=Path(output).name, style="DialogFile.TLabel", wraplength=420).grid(
            row=1, column=1, sticky="ew", pady=(6, 0)
        )

        actions = ttk.Frame(box, style="Card.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="e", pady=(20, 0))
        ttk.Button(actions, text="打开文件位置", command=lambda: self._open_file_location(output)).grid(
            row=0, column=0, padx=(0, 10)
        )
        ttk.Button(actions, text="关闭", command=dialog.destroy, style="Accent.TButton").grid(row=0, column=1)

        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.update_idletasks()
        self._center_on_root(dialog)
        dialog.focus_set()

    def _center_on_root(self, window: tk.Toplevel):
        self.root.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_width = self.root.winfo_width()
        root_height = self.root.winfo_height()
        x = root_x + max((root_width - width) // 2, 0)
        y = root_y + max((root_height - height) // 2, 0)
        window.geometry(f"+{x}+{y}")

    def _open_file_location(self, output: str):
        path = Path(output)
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer.exe", f"/select,{path}"])
            else:
                os.startfile(str(path.parent))
        except Exception as exc:
            self._log(f"打开文件位置失败：{exc}\n")
            try:
                os.startfile(str(path.parent))
            except Exception:
                pass


def main():
    enable_dpi_awareness()
    root_class = TkinterDnD.Tk if DND_AVAILABLE else tk.Tk
    root = root_class()
    VerticalWrapperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
