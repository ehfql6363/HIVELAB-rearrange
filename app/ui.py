from __future__ import annotations
import queue
import threading
from pathlib import Path
from tkinter import Tk, ttk, filedialog, StringVar, IntVar, END, DISABLED, NORMAL, colorchooser
from tkinter import messagebox
import tkinter as tk
import os, sys, subprocess

from .controller import AppController
from .settings import load_settings, save_settings
from .i18n_loader import _, set_locale

class AppUI:
    def __init__(self, root: Tk):
        self.root = root
        self._last_target_root = ""
        self.settings = load_settings()
        lang = self.settings.get("locale", "ko")
        set_locale(lang)
        self.controller = AppController(self.settings)

        self.root.title(_("HIVELAB Rearrange"))
        w = self.settings.get("window", {}).get("width", 1000)
        h = self.settings.get("window", {}).get("height", 720)
        self.root.geometry(f"{w}x{h}")

        # state
        self.running = False
        self.progress_var = IntVar(value=0)
        self.status_var = StringVar(value=_("Ready"))
        self.input_dir_var = StringVar(value=self.settings.get("last_input_dir", ""))
        self.job_var = StringVar(value="")

        self.executor = threading.Thread
        self.ui_queue: queue.Queue[tuple[str, dict]] = queue.Queue()

        self._build_menu()
        self._build_scroll_container()
        self._build_content()
        self._build_params_panel()
        self._wire_queue_pump()

        job_names = self.controller.list_job_names()
        if job_names:
            self.job_combo['values'] = job_names
            self.job_combo.set(job_names[0])
            self._render_params_for_job()

    # Menu
    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label=_("Exit"), command=self.root.destroy)
        menubar.add_cascade(label=_("File"), menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=_("About"), command=self._show_about)
        menubar.add_cascade(label=_("Help"), menu=help_menu)

        self.root.config(menu=menubar)

    # Whole-window scroll container
    def _build_scroll_container(self):
        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0)
        self._vbar = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vbar.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        self._vbar.pack(side="right", fill="y")

        self._content = ttk.Frame(self._canvas)
        self._content_id = self._canvas.create_window((0, 0), window=self._content, anchor="nw")

        self._content.bind("<Configure>", self._on_content_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        self._bind_mousewheel(self._canvas)

        self.status = ttk.Label(self.root, text=_("Ready"), anchor="w")
        self.status.pack(fill="x", side="bottom")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Accent.TButton", padding=6)

    def _on_content_configure(self, event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._content_id, width=event.width)

    def _bind_mousewheel(self, widget: tk.Widget):
        widget.bind_all("<MouseWheel>", self._on_mousewheel)
        widget.bind_all("<Button-4>", self._on_mousewheel_linux)
        widget.bind_all("<Button-5>", self._on_mousewheel_linux)

    def _add_tooltip(self, widget: tk.Widget, text: str):
        tip = {"win": None}

        def show(_e=None):
            if tip["win"] is not None:
                return
            x = widget.winfo_rootx() + 16
            y = widget.winfo_rooty() + widget.winfo_height() + 6
            win = tk.Toplevel(widget)
            win.wm_overrideredirect(True)
            win.wm_geometry(f"+{x}+{y}")
            ttk.Label(win, text=text, padding=8, relief="solid", borderwidth=1).pack()
            tip["win"] = win

        def hide(_e=None):
            if tip["win"] is not None:
                tip["win"].destroy()
                tip["win"] = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)
        widget.bind("<FocusOut>", hide)

    def _bind_text_scroll(self, text_widget: tk.Text):
        """마우스 포인터가 텍스트 위에 있을 때는 텍스트만 스크롤하게 한다."""

        def on_wheel(event):
            # Windows/Mac: event.delta, Up=+120, Down=-120
            direction = -1 if getattr(event, "delta", 0) > 0 else 1
            text_widget.yview_scroll(direction, "units")
            return "break"  # 더 이상 캔버스로 전파되지 않음

        # Windows / macOS
        text_widget.bind("<MouseWheel>", on_wheel)
        # Linux(X11)
        text_widget.bind("<Button-4>", lambda e: (text_widget.yview_scroll(-1, "units"), "break"))
        text_widget.bind("<Button-5>", lambda e: (text_widget.yview_scroll(1, "units"), "break"))

    def _on_mousewheel(self, event):
        delta = -1 if event.delta > 0 else 1
        self._canvas.yview_scroll(delta, "units")

    def _on_mousewheel_linux(self, event):
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")

    # Content
    def _build_content(self):
        pad = 10
        frm = ttk.Frame(self._content, padding=pad)
        frm.pack(fill="both", expand=True)

        # Job row
        row2 = ttk.Frame(frm)
        row2.pack(fill="x", pady=(8, 4))
        ttk.Label(row2, text=_("Job")).pack(side="left")
        self.job_combo = ttk.Combobox(row2, textvariable=self.job_var, state="readonly", width=40)
        self.job_combo.pack(side="left", padx=6)
        self.job_combo.bind("<<ComboboxSelected>>", lambda e: self._render_params_for_job())

        # Buttons row
        row3 = ttk.Frame(frm)
        row3.pack(fill="x", pady=(8, 4))
        self.start_btn = ttk.Button(row3, text=_("Start"), command=self._start, style="Accent.TButton")
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(row3, text=_("Cancel"), command=self._cancel, state=DISABLED)
        self.cancel_btn.pack(side="left", padx=(6, 0))

        # 로그 지우기 / 완료 폴더 열기
        self.clear_log_btn = ttk.Button(row3, text=_("Clear log"), command=self._clear_log)
        self.clear_log_btn.pack(side="left", padx=(12, 0))
        self.open_target_btn = ttk.Button(row3, text=_("Open target root..."), command=self._open_target_root,
                                          state=DISABLED)
        self.open_target_btn.pack(side="left", padx=(6, 0))

        # Progress
        row4 = ttk.Frame(frm)
        row4.pack(fill="x", pady=(8, 4))
        ttk.Label(row4, textvariable=self.status_var).pack(side="left")
        self.pbar = ttk.Progressbar(row4, variable=self.progress_var, maximum=100)
        self.pbar.pack(side="left", padx=10, fill="x", expand=True)

        # Parameters group container
        self.params_group = ttk.LabelFrame(frm, text=_("Parameters"))
        self.params_group.pack(fill="both", expand=True, pady=(10, 10))
        self.params_frame = ttk.Frame(self.params_group)
        self.params_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Log
        log_frame = ttk.Frame(frm)
        log_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.log = tk.Text(log_frame, height=16, wrap="word", state=DISABLED)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        self._bind_text_scroll(self.log)

    # Params Panel
    def _build_params_panel(self):
        self.params_widgets = {}

    def _clear_params(self):
        for w in self.params_frame.winfo_children():
            w.destroy()
        self.params_widgets.clear()

    def _browse_to(self, var: tk.StringVar):
        chosen = filedialog.askdirectory(title=_("Choose folder"))
        if chosen:
            var.set(chosen)

    def _render_params_for_job(self):
        self._clear_params()
        job_name = self.job_combo.get().strip()
        if not job_name:
            return
        try:
            job_cls = self.controller.get_job_by_name(job_name)
        except Exception:
            return
        needs = getattr(job_cls, "meta")().get("needs_params")
        pad = {"padx": 6, "pady": 4}

        if needs == "rearrange":
            row = 0
            ttk.Label(self.params_frame, text=_("Source A folder")).grid(row=row, column=0, sticky="w", **pad)
            self.params_widgets["A_root"] = tk.StringVar()
            ttk.Entry(self.params_frame, textvariable=self.params_widgets["A_root"], width=60).grid(row=row, column=1, sticky="ew", **pad)
            ttk.Button(self.params_frame, text=_("Browse..."), command=lambda: self._browse_to(self.params_widgets["A_root"])).grid(row=row, column=2, **pad)

            row += 1
            ttk.Label(self.params_frame, text=_("Source B folder")).grid(row=row, column=0, sticky="w", **pad)
            self.params_widgets["B_root"] = tk.StringVar()
            ttk.Entry(self.params_frame, textvariable=self.params_widgets["B_root"], width=60).grid(row=row, column=1, sticky="ew", **pad)
            ttk.Button(self.params_frame, text=_("Browse..."), command=lambda: self._browse_to(self.params_widgets["B_root"])).grid(row=row, column=2, **pad)

            row += 1
            ttk.Label(self.params_frame, text=_("Target root folder")).grid(row=row, column=0, sticky="w", **pad)
            self.params_widgets["target_root"] = tk.StringVar(
                value=self.settings.get("last_target_root", "")
            )
            ttk.Entry(self.params_frame, textvariable=self.params_widgets["target_root"], width=60).grid(row=row, column=1, sticky="ew", **pad)
            ttk.Button(self.params_frame, text=_("Browse..."), command=lambda: self._browse_to(self.params_widgets["target_root"])).grid(row=row, column=2, **pad)

            def _toggle_open_btn(*_):
                v = (self.params_widgets["target_root"].get() or "").strip()
                self.open_target_btn.config(state=(NORMAL if v else DISABLED))

            self.params_widgets["target_root"].trace_add("write", _toggle_open_btn)
            _toggle_open_btn()

            # Dry-run
            row += 1
            self.params_widgets["dry_run"] = tk.BooleanVar(value=True)
            dry_row = ttk.Frame(self.params_frame)
            dry_row.grid(row=row, column=0, columnspan=3, sticky="w", **pad)

            cb = ttk.Checkbutton(dry_row, text=_("Dry-run (no changes)"),
                                 variable=self.params_widgets["dry_run"])
            cb.pack(side="left")

            info = ttk.Label(dry_row, text="(?)")
            info.pack(side="left", padx=(6, 0))

            # 툴팁 연결(체크박스/아이콘 둘 다)
            tip_text = _("No files will be copied or created; only a plan is logged.")
            self._add_tooltip(cb, tip_text)
            self._add_tooltip(info, tip_text)

            # ---- NEW: permutation controls + watermark panel (side-by-side) ----
            row += 1
            ttk.Separator(self.params_frame, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="ew",
                                                                       **pad)

            row += 1
            container = ttk.Frame(self.params_frame)
            container.grid(row=row, column=0, columnspan=4, sticky="nsew", **pad)
            container.grid_columnconfigure(0, weight=1)  # 왼쪽(순열/시드/소그룹)
            container.grid_columnconfigure(1, weight=1)  # 오른쪽(워터마크 옵션)

            # ---------- LEFT: 순열 모드 / 시드 / 소그룹 순열 ----------
            perm_left = ttk.Frame(container)
            perm_left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

            r = 0
            ttk.Label(perm_left, text=_("순열 모드")).grid(row=r, column=0, sticky="w", **pad)
            self.params_widgets["perm_mode"] = tk.StringVar(value="manual")
            m1 = ttk.Radiobutton(perm_left, text=_("수동"), value="manual", variable=self.params_widgets["perm_mode"])
            m2 = ttk.Radiobutton(perm_left, text=_("랜덤(시드)"), value="random", variable=self.params_widgets["perm_mode"])
            m1.grid(row=r, column=1, sticky="w", **pad)
            m2.grid(row=r, column=2, sticky="w", **pad)

            r += 1
            ttk.Label(perm_left, text=_("시드")).grid(row=r, column=0, sticky="w", **pad)
            self.params_widgets["rand_seed"] = tk.StringVar(value="")
            seed_entry = ttk.Entry(perm_left, textvariable=self.params_widgets["rand_seed"], width=20)
            seed_entry.grid(row=r, column=1, sticky="w", **pad)

            r += 1
            ttk.Label(perm_left, text=_("소그룹 순열")).grid(row=r, column=0, sticky="w", **pad)

            def perm_strings(base):
                b = list(base)
                return [
                    f"{b[0]}-{b[1]}-{b[2]}",
                    f"{b[0]}-{b[2]}-{b[1]}",
                    f"{b[1]}-{b[0]}-{b[2]}",
                    f"{b[1]}-{b[2]}-{b[0]}",
                    f"{b[2]}-{b[0]}-{b[1]}",
                    f"{b[2]}-{b[1]}-{b[0]}",
                ]

            # ㄱ: A(1,2,3)
            r += 1
            ttk.Label(perm_left, text=_("그룹 ㄱ (A1–3)")).grid(row=r, column=0, sticky="w", **pad)
            self.params_widgets["perm_k"] = tk.StringVar(value="3-1-2")
            cb_k = ttk.Combobox(perm_left, textvariable=self.params_widgets["perm_k"],
                                values=perm_strings([1, 2, 3]), state="readonly", width=12)
            cb_k.grid(row=r, column=1, sticky="w", **pad)

            # ㄴ: A(4,5,6)
            r += 1
            ttk.Label(perm_left, text=_("그룹 ㄴ (A4–6)")).grid(row=r, column=0, sticky="w", **pad)
            self.params_widgets["perm_n"] = tk.StringVar(value="6-4-5")
            cb_n = ttk.Combobox(perm_left, textvariable=self.params_widgets["perm_n"],
                                values=perm_strings([4, 5, 6]), state="readonly", width=12)
            cb_n.grid(row=r, column=1, sticky="w", **pad)

            # ㄷ: B(1,2,3)
            r += 1
            ttk.Label(perm_left, text=_("그룹 ㄷ (B1–3)")).grid(row=r, column=0, sticky="w", **pad)
            self.params_widgets["perm_d"] = tk.StringVar(value="2-3-1")
            cb_d = ttk.Combobox(perm_left, textvariable=self.params_widgets["perm_d"],
                                values=perm_strings([1, 2, 3]), state="readonly", width=12)
            cb_d.grid(row=r, column=1, sticky="w", **pad)

            # ㄹ: B(4,5,6)
            r += 1
            ttk.Label(perm_left, text=_("그룹 ㄹ (B4–6)")).grid(row=r, column=0, sticky="w", **pad)
            self.params_widgets["perm_r"] = tk.StringVar(value="5-6-4")
            cb_r = ttk.Combobox(perm_left, textvariable=self.params_widgets["perm_r"],
                                values=perm_strings([4, 5, 6]), state="readonly", width=12)
            cb_r.grid(row=r, column=1, sticky="w", **pad)

            # 라디오와 시드 활성/비활성 연동
            self.params_widgets["perm_cbs"] = [cb_k, cb_n, cb_d, cb_r]

            def _update_perm_widgets_state(*_):
                mode = self.params_widgets["perm_mode"].get()
                if mode == "manual":
                    for cb in self.params_widgets["perm_cbs"]:
                        cb.config(state="readonly")
                    seed_entry.config(state="disabled")
                else:
                    for cb in self.params_widgets["perm_cbs"]:
                        cb.config(state="disabled")
                    seed_entry.config(state="normal")

            _update_perm_widgets_state()
            self.params_widgets["perm_mode"].trace_add("write", _update_perm_widgets_state)

            # ---------- RIGHT: 워터마크 옵션 ----------
            wm_right = ttk.LabelFrame(container, text=_("워터마크 옵션"))
            wm_right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
            for c in range(5):  # ← column=4도 쓰니 5칸 잡기
                wm_right.grid_columnconfigure(c, weight=1)

            # 0) 사용 여부
            self.params_widgets["wm_enabled"] = tk.BooleanVar(value=False)
            wm_enabled_chk = ttk.Checkbutton(wm_right, text=_("워터마크 적용"),
                                             variable=self.params_widgets["wm_enabled"])
            wm_enabled_chk.grid(row=0, column=0, sticky="w", padx=6, pady=4)

            # 1) 텍스트
            ttk.Label(wm_right, text=_("텍스트")).grid(row=1, column=0, sticky="w", padx=6, pady=4)
            self.params_widgets["wm_text"] = tk.StringVar(value="")
            wm_text_entry = ttk.Entry(wm_right, textvariable=self.params_widgets["wm_text"])
            wm_text_entry.grid(row=1, column=1, columnspan=4, sticky="ew", padx=6, pady=4)

            # 2) 폰트 파일
            ttk.Label(wm_right, text=_("폰트 파일(.ttf/.otf)")).grid(row=2, column=0, sticky="w", padx=6, pady=4)
            self.params_widgets["wm_font_path"] = tk.StringVar(value="")
            wm_font_entry = ttk.Entry(wm_right, textvariable=self.params_widgets["wm_font_path"])
            wm_font_entry.grid(row=2, column=1, columnspan=3, sticky="ew", padx=6, pady=4)
            wm_font_btn = ttk.Button(wm_right, text=_("찾아보기..."),
                                     command=lambda: self._browse_font(self.params_widgets["wm_font_path"]))
            wm_font_btn.grid(row=2, column=4, padx=6, pady=4)

            # 3) 색/불투명/크기
            ttk.Label(wm_right, text=_("색상")).grid(row=3, column=0, sticky="w", padx=6, pady=4)
            self.params_widgets["wm_color"] = tk.StringVar(value="#FFFFFF")
            color_swatch = tk.Label(wm_right, width=2, relief="solid", borderwidth=1,
                                    background=self.params_widgets["wm_color"].get())
            color_swatch.grid(row=3, column=1, sticky="w", padx=(6, 2), pady=4)
            wm_color_btn = ttk.Button(wm_right, text=_("선택"),
                                      command=lambda: self._pick_color(self.params_widgets["wm_color"], color_swatch))
            wm_color_btn.grid(row=3, column=2, sticky="w", padx=6, pady=4)

            ttk.Label(wm_right, text=_("불투명도(%)")).grid(row=3, column=3, sticky="e", padx=6, pady=4)
            self.params_widgets["wm_opacity"] = tk.IntVar(value=50)
            wm_opacity_sp = ttk.Spinbox(wm_right, from_=0, to=100,
                                        textvariable=self.params_widgets["wm_opacity"], width=5)
            wm_opacity_sp.grid(row=3, column=4, sticky="w", padx=6, pady=4)

            ttk.Label(wm_right, text=_("폰트 크기(px)")).grid(row=4, column=0, sticky="w", padx=6, pady=4)
            self.params_widgets["wm_font_size"] = tk.IntVar(value=36)
            wm_fontsize_sp = ttk.Spinbox(wm_right, from_=6, to=512,
                                         textvariable=self.params_widgets["wm_font_size"], width=6)
            wm_fontsize_sp.grid(row=4, column=1, sticky="w", padx=6, pady=4)

            # 4) 위치 + 오프셋
            ttk.Label(wm_right, text=_("초기 위치")).grid(row=4, column=2, sticky="e", padx=6, pady=4)
            self.params_widgets["wm_position"] = tk.StringVar(value="bottom-right")
            wm_pos_combo = ttk.Combobox(wm_right, state="readonly", width=12,
                                        textvariable=self.params_widgets["wm_position"],
                                        values=["top-left", "top-right", "bottom-left", "bottom-right", "center"])
            wm_pos_combo.grid(row=4, column=3, sticky="w", padx=6, pady=4)

            ttk.Label(wm_right, text=_("오프셋 X/Y(px)")).grid(row=5, column=0, sticky="w", padx=6, pady=4)
            self.params_widgets["wm_offset_x"] = tk.IntVar(value=16)
            self.params_widgets["wm_offset_y"] = tk.IntVar(value=16)
            wm_offx_sp = ttk.Spinbox(wm_right, from_=-2000, to=2000,
                                     textvariable=self.params_widgets["wm_offset_x"], width=7)
            wm_offx_sp.grid(row=5, column=1, sticky="w", padx=6, pady=4)
            wm_offy_sp = ttk.Spinbox(wm_right, from_=-2000, to=2000,
                                     textvariable=self.params_widgets["wm_offset_y"], width=7)
            wm_offy_sp.grid(row=5, column=2, sticky="w", padx=6, pady=4)

            # 5) 외곽선
            self.params_widgets["wm_outline"] = tk.BooleanVar(value=True)
            wm_outline_chk = ttk.Checkbutton(wm_right, text=_("외곽선"),
                                             variable=self.params_widgets["wm_outline"])
            wm_outline_chk.grid(row=6, column=0, sticky="w", padx=6, pady=4)
            ttk.Label(wm_right, text=_("두께(px)")).grid(row=6, column=1, sticky="w", padx=6, pady=4)
            self.params_widgets["wm_outline_width"] = tk.IntVar(value=2)
            wm_outline_w_sp = ttk.Spinbox(wm_right, from_=1, to=20,
                                          textvariable=self.params_widgets["wm_outline_width"], width=5)
            wm_outline_w_sp.grid(row=6, column=2, sticky="w", padx=6, pady=4)

            # ← 여기서 한 번에 등록!
            self.params_widgets["wm_widgets"] = [
                wm_enabled_chk, wm_text_entry,
                wm_font_entry, wm_font_btn,
                wm_color_btn, wm_opacity_sp,
                wm_fontsize_sp, wm_pos_combo,
                wm_offx_sp, wm_offy_sp,
                wm_outline_chk, wm_outline_w_sp
            ]

            # Targets header
            saved_targets = self.settings.get("last_targets", [])

            row += 1
            ttk.Separator(self.params_frame, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="ew", **pad)

            row += 1
            ttk.Label(self.params_frame, text=_("Targets (12)")).grid(row=row, column=0, sticky="w", **pad)
            row += 1
            ttk.Label(self.params_frame, text="#").grid(row=row, column=0, sticky="w", **pad)
            ttk.Label(self.params_frame, text=_("Name (create under Target Root)")).grid(row=row, column=1, sticky="w", **pad)
            ttk.Label(self.params_frame, text=_("Or use existing folder path")).grid(row=row, column=2, sticky="w", **pad)

            self.params_widgets["targets"] = []
            for i in range(12):
                row += 1
                ttk.Label(self.params_frame, text=str(i+1)).grid(row=row, column=0, sticky="w", **pad)
                name_var = tk.StringVar()
                path_var = tk.StringVar()

                if i < len(saved_targets):
                    name_var.set(saved_targets[i].get("name", ""))
                    path_var.set(saved_targets[i].get("path", ""))

                self.params_widgets["targets"].append((name_var, path_var))
                ttk.Entry(self.params_frame, textvariable=name_var, width=30).grid(row=row, column=1, sticky="ew", **pad)
                entry = ttk.Entry(self.params_frame, textvariable=path_var, width=45)
                entry.grid(row=row, column=2, sticky="ew", **pad)
                ttk.Button(self.params_frame, text=_("Browse..."), command=lambda v=path_var: self._browse_to(v)).grid(row=row, column=3, **pad)

            for c in range(4):
                self.params_frame.grid_columnconfigure(c, weight=1)
        else:
            ttk.Label(self.params_frame, text=_("This job has no additional parameters.")).pack(anchor="w", padx=10, pady=10)

    # Runtime
    def _wire_queue_pump(self):
        def pump():
            try:
                while True:
                    kind, payload = self.ui_queue.get_nowait()
                    if kind == "progress":
                        self.progress_var.set(int(payload.get("pct", 0)))
                        self.status_var.set(payload.get("msg", ""))
                        self.status.config(text=self.status_var.get())
                    elif kind == "log":
                        self._log(payload.get("text", ""))
                    elif kind == "done":
                        logs = getattr(self, "_last_context", {}).get("_ui_logs", [])
                        for line in logs:
                            self._log(str(line))
                        getattr(self, "_last_context", {}).pop("_ui_logs", None)

                        ok = payload.get("ok", False)
                        err = payload.get("err", "")
                        if ok:
                            self._log(_("Done."))
                            self.status_var.set(_("Done."))
                        else:
                            self._log(_("Error: ") + str(err))
                            self.status_var.set(_("Failed"))
                        self._set_running(False)

            except Exception:
                pass
            finally:
                self.root.after(100, pump)
        self.root.after(100, pump)

    def _set_running(self, flag: bool):
        self.running = flag
        self.start_btn.config(state=DISABLED if flag else NORMAL)
        self.cancel_btn.config(state=NORMAL if flag else DISABLED)
        # 워터마크 위젯 비/활성
        for w in self.params_widgets.get("wm_widgets", []):
            self._set_widget_enabled(w, not flag)

    def _set_widget_enabled(self, widget, enabled: bool):
        try:
            if isinstance(widget, ttk.Combobox):
                widget.config(state=("readonly" if enabled else "disabled"))
            else:
                widget.config(state=("normal" if enabled else "disabled"))
        except Exception:
            pass

    def _log(self, text: str):
        self.log.config(state=tk.NORMAL)
        self.log.insert(END, text + "\n")
        self.log.see(END)
        self.log.config(state=tk.DISABLED)

    def _show_about(self):
        messagebox.showinfo(_("About"), "YourApp\nA flexible desktop tool skeleton.")

    def _start(self):
        if self.running:
            return

        job_name = self.job_combo.get().strip()
        if not job_name:
            self._log(_("Please choose a job."))
            return

        self._set_running(True)
        self.progress_var.set(0)
        self.status_var.set(_("Running..."))

        context = {
            "settings": self.settings
        }

        try:
            job_cls = self.controller.get_job_by_name(job_name)
            needs = getattr(job_cls, "meta")().get("needs_params")
        except Exception:
            needs = None

        if needs == "rearrange":
            params = {
                "A_root": self.params_widgets.get("A_root").get() if self.params_widgets.get("A_root") else "",
                "B_root": self.params_widgets.get("B_root").get() if self.params_widgets.get("B_root") else "",
                "target_root": self.params_widgets.get("target_root").get() if self.params_widgets.get("target_root") else "",
                "dry_run": bool(self.params_widgets.get("dry_run").get()) if self.params_widgets.get("dry_run") else True,
                # NEW: permutation params
                "perm_mode": self.params_widgets.get("perm_mode").get() if self.params_widgets.get("perm_mode") else "manual",
                "perm_k": self.params_widgets.get("perm_k").get() if self.params_widgets.get("perm_k") else "3-1-2",
                "perm_n": self.params_widgets.get("perm_n").get() if self.params_widgets.get("perm_n") else "6-4-5",
                "perm_d": self.params_widgets.get("perm_d").get() if self.params_widgets.get("perm_d") else "2-3-1",
                "perm_r": self.params_widgets.get("perm_r").get() if self.params_widgets.get("perm_r") else "5-6-4",
                "rand_seed": self.params_widgets.get("rand_seed").get() if self.params_widgets.get("rand_seed") else "",
                "targets": [],
                "watermark": {
                    "enabled": bool(self.params_widgets.get("wm_enabled").get()),
                    "text": self.params_widgets.get("wm_text").get(),
                    "font_path": self.params_widgets.get("wm_font_path").get(),
                    "color": self.params_widgets.get("wm_color").get(),  # "#RRGGBB"
                    "opacity": int(self.params_widgets.get("wm_opacity").get()),  # 0~100
                    "font_size": int(self.params_widgets.get("wm_font_size").get()),
                    "position": self.params_widgets.get("wm_position").get(),  # preset
                    "offset_x": int(self.params_widgets.get("wm_offset_x").get()),
                    "offset_y": int(self.params_widgets.get("wm_offset_y").get()),
                    "outline": bool(self.params_widgets.get("wm_outline").get()),
                    "outline_width": int(self.params_widgets.get("wm_outline_width").get()),
                },

            }
            for name_var, path_var in self.params_widgets.get("targets", []):
                params["targets"].append({"name": name_var.get(), "path": path_var.get()})
            context["params"] = params

            self.settings["last_target_root"] = params.get("target_root", "")
            self.settings["last_targets"] = params.get("targets", [])
            save_settings(self.settings)

            self._last_target_root = params.get("target_root", "")
            self.open_target_btn.config(state=(NORMAL if self._last_target_root else DISABLED))

        def progress_cb(pct: int, msg: str):
            self.ui_queue.put(("progress", {"pct": pct, "msg": msg}))

        def done_cb(ok: bool, err: str):
            self.ui_queue.put(("done", {"ok": ok, "err": err}))

        self.open_target_btn.config(state=(NORMAL if self._last_target_root else DISABLED))

        self._last_context = context
        target = self.controller.run_job(job_name, context, progress_cb, done_cb)
        t = self.executor(target=target, daemon=True)
        t.start()

    def _cancel(self):
        if self.controller.cancel():
            self._log("Cancelling...")

    def _clear_log(self):
        self.log.config(state=tk.NORMAL)
        self.log.delete("1.0", END)
        self.log.config(state=tk.DISABLED)

    def _open_in_explorer(self, path: Path):
        if not path.exists():
            messagebox.showerror(_("Open"), _("Path does not exist: ") + str(path))
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror(_("Open"), str(e))

    def _open_results(self):
        paths = getattr(self, "_last_result_dirs", [])
        # 결과 없으면 안내
        if not paths:
            messagebox.showinfo(_("Open results"), _("No result folders from the last run (or it was a dry-run)."))
            return
        # 1개면 바로 오픈
        if len(paths) == 1:
            self._open_in_explorer(Path(paths[0]))
            return
        # 여러 개면 선택 창 띄우기
        top = tk.Toplevel(self.root)
        top.title(_("Open results"))
        top.geometry("520x360")
        ttk.Label(top, text=_("Choose a folder to open:")).pack(anchor="w", padx=12, pady=(12, 6))
        lb = tk.Listbox(top, height=12)
        for p in paths:
            lb.insert(END, p)
        lb.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        btn_frame = ttk.Frame(top)
        btn_frame.pack(fill="x", padx=12, pady=(0, 12))

        def _open_selected():
            sel = lb.curselection()
            if not sel:
                return
            self._open_in_explorer(Path(paths[sel[0]]))

        ttk.Button(btn_frame, text=_("Open"), command=_open_selected).pack(side="right")

    def _open_target_root(self):
        # UI에 값이 있으면 그걸 우선 사용, 없으면 저장된 최근 값 사용
        path_str = ""
        trg_var = self.params_widgets.get("target_root")
        if trg_var:
            path_str = (trg_var.get() or "").strip()
        if not path_str:
            path_str = (self.settings.get("last_target_root") or "").strip()

        if not path_str:
            messagebox.showinfo(_("Open target root"), _("Please set Target root folder first."))
            return

        self._open_in_explorer(Path(path_str))

    def _browse_font(self, var: tk.StringVar):
        chosen = filedialog.askopenfilename(
            title=_("폰트 파일 선택"),
            filetypes=[("Font files", "*.ttf *.otf"), ("All files", "*.*")]
        )
        if chosen:
            var.set(chosen)

    def _pick_color(self, var: tk.StringVar, swatch: tk.Label):
        initial = var.get() or "#000000"
        color = colorchooser.askcolor(initialcolor=initial)[1]
        if color:
            var.set(color)
            # 미니 미리보기
            swatch.config(background=color)


def run():
    root = Tk()
    AppUI(root)
    root.mainloop()
