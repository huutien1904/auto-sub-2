"""API Settings dialog — translation providers + TTS/dubbing API keys."""

import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

import config as cfg


class ApiSettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_saved=None):
        super().__init__(parent)

        self.title("Cài đặt API")
        self.geometry("580x580")
        self.resizable(False, False)
        self.grab_set()

        self._on_saved = on_saved
        self._data = cfg.load()

        self._build_ui()
        self._load_into_ui()
        self.after(50, self._center)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        ctk.CTkLabel(
            self,
            text="Cài đặt API",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(pady=(16, 2))

        # Tabs
        self._tabs = ctk.CTkTabview(self, height=420)
        self._tabs.pack(fill="both", expand=True, padx=16, pady=(4, 0))
        self._tabs.add("🌐  Dịch thuật")
        self._tabs.add("🎙  Lồng tiếng")

        self._build_translation_tab(self._tabs.tab("🌐  Dịch thuật"))
        self._build_dubbing_tab(self._tabs.tab("🎙  Lồng tiếng"))

        # Bottom bar
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(6, 12))

        self._test_btn = ctk.CTkButton(
            btn_frame,
            text="🔌  Kiểm tra kết nối",
            width=170,
            fg_color=("#1565C0", "#0D47A1"),
            hover_color=("#0D47A1", "#082a60"),
            command=self._test_connection,
        )
        self._test_btn.pack(side="left")

        ctk.CTkButton(
            btn_frame, text="Hủy", width=80,
            fg_color=("gray65", "gray35"), hover_color=("gray55", "gray45"),
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btn_frame, text="💾  Lưu", width=80,
            fg_color="#2E7D32", hover_color="#1B5E20",
            command=self._save,
        ).pack(side="right")

        self._status_lbl = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11))
        self._status_lbl.pack(pady=(0, 4))

    # ── Translation tab ───────────────────────────────────────────────────────

    def _build_translation_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            tab, text="Nhà cung cấp:", font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")

        self._provider_var = ctk.StringVar()
        ctk.CTkOptionMenu(
            tab,
            variable=self._provider_var,
            values=list(cfg.PROVIDER_LABELS.values()),
            width=280,
            command=self._on_provider_change,
        ).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")

        # OpenAI frame
        self._openai_frame = ctk.CTkFrame(tab)
        self._openai_frame.grid_columnconfigure(0, weight=1)
        self._build_key_section(
            self._openai_frame,
            label="OpenAI API Key:",
            placeholder="sk-...",
            key_attr="_openai_key_var",
            entry_attr="_openai_key_entry",
            row_start=0,
        )
        ctk.CTkLabel(
            self._openai_frame, text="Model:",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=2, column=0, padx=12, pady=(6, 2), sticky="w")
        self._openai_model_var = ctk.StringVar()
        ctk.CTkOptionMenu(
            self._openai_frame, variable=self._openai_model_var,
            values=cfg.openai_models(), width=220,
        ).grid(row=3, column=0, padx=12, pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            self._openai_frame,
            text="gpt-4o-mini: nhanh & rẻ  |  gpt-4o: chính xác nhất",
            font=ctk.CTkFont(size=11), text_color=("gray50", "gray60"),
        ).grid(row=4, column=0, padx=12, pady=(0, 10), sticky="w")

        # Claude frame
        self._claude_frame = ctk.CTkFrame(tab)
        self._claude_frame.grid_columnconfigure(0, weight=1)
        self._build_key_section(
            self._claude_frame,
            label="Anthropic API Key:",
            placeholder="sk-ant-...",
            key_attr="_claude_key_var",
            entry_attr="_claude_key_entry",
            row_start=0,
        )
        ctk.CTkLabel(
            self._claude_frame, text="Model:",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=2, column=0, padx=12, pady=(6, 2), sticky="w")
        self._claude_model_var = ctk.StringVar()
        ctk.CTkOptionMenu(
            self._claude_frame, variable=self._claude_model_var,
            values=cfg.anthropic_models(), width=290,
        ).grid(row=3, column=0, padx=12, pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            self._claude_frame,
            text="Haiku: nhanh & rẻ  |  Sonnet: cân bằng  |  Opus: tốt nhất",
            font=ctk.CTkFont(size=11), text_color=("gray50", "gray60"),
        ).grid(row=4, column=0, padx=12, pady=(0, 10), sticky="w")

        # Google frame
        self._google_frame = ctk.CTkFrame(tab)
        ctk.CTkLabel(
            self._google_frame,
            text="Google Translate không cần API key.\nDịch miễn phí nhưng chất lượng thấp hơn AI.",
            font=ctk.CTkFont(size=13), justify="left",
        ).pack(padx=20, pady=20)

    # ── Dubbing tab ───────────────────────────────────────────────────────────

    def _build_dubbing_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            tab,
            text="FPT.AI — giọng tiếng Việt vùng miền (Bắc / Trung / Nam)",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")

        self._build_key_section(
            tab,
            label="FPT.AI API Key:",
            placeholder="Lấy miễn phí tại fpt.ai/aiapi",
            key_attr="_fptai_key_var",
            entry_attr="_fptai_key_entry",
            row_start=1,
        )

        ctk.CTkLabel(
            tab,
            text="▸ Miễn phí 5.000 ký tự/ngày\n"
                 "▸ Đăng ký tại fpt.ai → AI API → Text to Speech\n"
                 "▸ Có 6 giọng: Nam/Nữ Bắc · Nam/Nữ Nam · Nam/Nữ Nam trẻ",
            font=ctk.CTkFont(size=12),
            text_color=("gray45", "gray65"),
            justify="left",
        ).grid(row=3, column=0, padx=14, pady=(4, 10), sticky="w")

        # OpenAI TTS note
        ctk.CTkFrame(tab, height=1, fg_color=("gray75", "gray35")).grid(
            row=4, column=0, padx=12, pady=6, sticky="ew"
        )
        ctk.CTkLabel(
            tab,
            text="OpenAI TTS — nếu đã có OpenAI API key ở tab Dịch thuật,\n"
                 "chọn 'OpenAI TTS' trong phần Giọng lồng tiếng sẽ dùng key đó tự động.",
            font=ctk.CTkFont(size=12),
            text_color=("gray45", "gray65"),
            justify="left",
        ).grid(row=5, column=0, padx=14, pady=(0, 10), sticky="w")

    # ── Helper: build a labelled key entry + 👁 button ────────────────────────

    def _build_key_section(self, parent, label, placeholder, key_attr, entry_attr, row_start):
        ctk.CTkLabel(
            parent, text=label, font=ctk.CTkFont(weight="bold")
        ).grid(row=row_start, column=0, padx=12, pady=(8, 2), sticky="w")

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.grid(row=row_start + 1, column=0, padx=12, pady=(0, 4), sticky="ew")
        row.grid_columnconfigure(0, weight=1)

        var = tk.StringVar()
        setattr(self, key_attr, var)
        entry = ctk.CTkEntry(row, textvariable=var, placeholder_text=placeholder, show="•", width=380)
        entry.grid(row=0, column=0, sticky="ew")
        setattr(self, entry_attr, entry)

        ctk.CTkButton(
            row, text="👁", width=36,
            command=lambda e=entry: self._toggle_show(e),
        ).grid(row=0, column=1, padx=(6, 0))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _center(self):
        self.update_idletasks()
        pw = self.master.winfo_x() + self.master.winfo_width() // 2
        ph = self.master.winfo_y() + self.master.winfo_height() // 2
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{pw - w//2}+{ph - h//2}")

    def _load_into_ui(self):
        label = cfg.PROVIDER_LABELS.get(self._data["provider"], cfg.PROVIDER_LABELS["google"])
        self._provider_var.set(label)
        self._openai_key_var.set(self._data.get("openai_api_key", ""))
        self._openai_model_var.set(self._data.get("openai_model", "gpt-4o-mini"))
        self._claude_key_var.set(self._data.get("anthropic_api_key", ""))
        self._claude_model_var.set(self._data.get("anthropic_model", "claude-haiku-4-5-20251001"))
        self._fptai_key_var.set(self._data.get("fptai_api_key", ""))
        self._on_provider_change(label)

    def _on_provider_change(self, label: str):
        self._current_provider = next(
            (k for k, v in cfg.PROVIDER_LABELS.items() if v == label), "google"
        )
        for f in (self._google_frame, self._openai_frame, self._claude_frame):
            f.grid_forget()

        target = {"google": self._google_frame,
                  "openai": self._openai_frame,
                  "claude": self._claude_frame}[self._current_provider]
        target.grid(row=2, column=0, padx=12, pady=4, sticky="ew")
        self._status_lbl.configure(text="")

    def _toggle_show(self, entry: ctk.CTkEntry):
        entry.configure(show="" if entry.cget("show") == "•" else "•")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _collect(self) -> dict:
        return {
            "provider": self._current_provider,
            "openai_api_key": self._openai_key_var.get().strip(),
            "openai_model": self._openai_model_var.get(),
            "anthropic_api_key": self._claude_key_var.get().strip(),
            "anthropic_model": self._claude_model_var.get(),
            "fptai_api_key": self._fptai_key_var.get().strip(),
        }

    def _save(self):
        data = self._collect()
        provider = data["provider"]
        if provider == "openai" and not data["openai_api_key"]:
            messagebox.showwarning("Thiếu key", "Vui lòng nhập OpenAI API Key!", parent=self)
            return
        if provider == "claude" and not data["anthropic_api_key"]:
            messagebox.showwarning("Thiếu key", "Vui lòng nhập Anthropic API Key!", parent=self)
            return

        # Merge into existing config (preserves tts_provider etc.)
        existing = cfg.load()
        existing.update(data)
        cfg.save(existing)
        if self._on_saved:
            self._on_saved(existing)
        self.destroy()

    def _test_connection(self):
        active_tab = self._tabs.get()
        if "Lồng tiếng" in active_tab:
            key = self._fptai_key_var.get().strip()
            if not key:
                self._status_lbl.configure(text="Nhập FPT.AI API key trước.", text_color="gray")
                return
            self._test_btn.configure(state="disabled", text="Đang kiểm tra...")
            threading.Thread(target=self._do_test_fptai, args=(key,), daemon=True).start()
            return

        data = self._collect()
        provider = data["provider"]
        if provider == "google":
            self._status_lbl.configure(text="Google Translate không cần kiểm tra key.", text_color="gray")
            return
        self._test_btn.configure(state="disabled", text="Đang kiểm tra...")
        threading.Thread(target=self._do_test, args=(provider, data), daemon=True).start()

    def _do_test(self, provider, data):
        try:
            if provider == "openai":
                self._test_openai(data["openai_api_key"], data["openai_model"])
            elif provider == "claude":
                self._test_claude(data["anthropic_api_key"], data["anthropic_model"])
            self.after(0, lambda: self._status_lbl.configure(
                text="✅  Kết nối thành công!", text_color="#4CAF50"))
        except Exception as exc:
            msg = str(exc)[:120]
            self.after(0, lambda: self._status_lbl.configure(
                text=f"❌  {msg}", text_color="#EF5350"))
        finally:
            self.after(0, lambda: self._test_btn.configure(
                state="normal", text="🔌  Kiểm tra kết nối"))

    def _do_test_fptai(self, api_key: str):
        try:
            import requests
            r = requests.post(
                "https://api.fpt.ai/hmi/tts/v5",
                headers={"api-key": api_key, "voice": "myan",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data="Xin chào".encode("utf-8"), timeout=10,
            )
            data = r.json()
            if data.get("error", 1) != 0:
                raise RuntimeError(data.get("message", "Lỗi không xác định"))
            self.after(0, lambda: self._status_lbl.configure(
                text="✅  FPT.AI kết nối thành công!", text_color="#4CAF50"))
        except Exception as exc:
            msg = str(exc)[:120]
            self.after(0, lambda: self._status_lbl.configure(
                text=f"❌  {msg}", text_color="#EF5350"))
        finally:
            self.after(0, lambda: self._test_btn.configure(
                state="normal", text="🔌  Kiểm tra kết nối"))

    def _test_openai(self, api_key, model):
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("Chưa cài openai. Chạy: pip install openai")
        client = OpenAI(api_key=api_key)
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5,
        )

    def _test_claude(self, api_key, model):
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("Chưa cài anthropic. Chạy: pip install anthropic")
        client = anthropic.Anthropic(api_key=api_key)
        client.messages.create(
            model=model, max_tokens=5,
            messages=[{"role": "user", "content": "Hi"}],
        )
