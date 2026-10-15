"""
GeoHide DNS Manager - Graphical User Interface
Поддерживает два режима работы:
1. 🎯 Изолированный (Antigravity IDE, Antigravity 2.0 Desktop и CLI agy через локальный Smart Proxy)
2. 🌐 Глобальный (Для всей Windows через системный hosts и DNS-серверы)
С автоматическим обнаружением запущенной Antigravity и интерактивным диалогом перезапуска.
"""

import os
import sys
import time
import threading
import datetime
import ctypes
import tkinter as tk
from PIL import Image

import customtkinter as ctk

# Внутренние модули
import geohide_core
import antigravity_config
from local_proxy import GeoHideSmartProxy


# Проверка прав администратора и автоматическое повышение (UAC)
def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def elevate_if_needed():
    if sys.platform == "win32" and not is_admin():
        script_path = os.path.abspath(__file__)
        params = f'"{script_path}"'
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        if ret > 32:
            sys.exit(0)
        else:
            print("Предупреждение: Запуск без прав администратора. Для глобального режима могут потребоваться права.")


# Настройка темы CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class RestartConfirmDialog(ctk.CTkToplevel):
    """Модальное диалоговое окно с предупреждением о необходимости перезапуска Antigravity."""
    def __init__(self, parent, on_restart, on_later):
        super().__init__(parent)
        self.title("Внимание: Требуется перезапуск")
        self.geometry("540x260")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Центрирование относительно родителя
        parent.update_idletasks()
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw - 540) // 2
        y = py + (ph - 260) // 2
        self.geometry(f"540x260+{max(0, x)}+{max(0, y)}")

        self.on_restart = on_restart
        self.on_later = on_later

        self._create_widgets()

    def _create_widgets(self):
        self.grid_columnconfigure(0, weight=1)

        # Карточка с предупреждением
        frame = ctk.CTkFrame(self, corner_radius=12, fg_color=("#1f242c", "#161b22"))
        frame.pack(fill="both", expand=True, padx=16, pady=16)

        header_label = ctk.CTkLabel(
            frame,
            text="⚠️  Antigravity (Gemini) сейчас запущена",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f85149"
        )
        header_label.pack(anchor="w", padx=20, pady=(16, 8))

        desc_text = (
            "Для того чтобы Antigravity IDE, language_server и Antigravity 2.0 CLI (agy)\n"
            "применили новые настройки прокси и восстановили доступ к Gemini, необходимо\n"
            "перезапустить приложение.\n\n"
            "Перезапустить Antigravity прямо сейчас?"
        )
        desc_label = ctk.CTkLabel(
            frame,
            text=desc_text,
            font=ctk.CTkFont(size=12),
            text_color="#c9d1d9",
            justify="left"
        )
        desc_label.pack(anchor="w", padx=20, pady=(0, 16))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 16))
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        btn_restart = ctk.CTkButton(
            btn_frame,
            text="🚀  Перезапустить сейчас",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#238636",
            hover_color="#2ea043",
            height=38,
            corner_radius=8,
            command=self._handle_restart
        )
        btn_restart.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        btn_later = ctk.CTkButton(
            btn_frame,
            text="⏱️  Перезапустить позже",
            font=ctk.CTkFont(size=13),
            fg_color="#30363d",
            hover_color="#484f58",
            height=38,
            corner_radius=8,
            command=self._handle_later
        )
        btn_later.grid(row=0, column=1, padx=(8, 0), sticky="ew")

    def _handle_restart(self):
        self.destroy()
        if self.on_restart:
            self.on_restart()

    def _handle_later(self):
        self.destroy()
        if self.on_later:
            self.on_later()


class GeoHideApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("GeoHide DNS Manager")
        self.geometry("780x740")
        self.minsize(720, 680)

        self._center_window(780, 740)
        self._setup_icon()

        self.is_busy = False
        self.auto_refresh_enabled = True
        self.active_mode = "isolated"

        # Локальный Smart Proxy сервер
        self.smart_proxy = GeoHideSmartProxy(
            host="127.0.0.1",
            port=8899,
            log_callback=lambda msg: self.log(msg, level="PROXY")
        )

        self._create_widgets()

        # Восстановление работы прокси, если он уже был включен в Antigravity
        if antigravity_config.is_antigravity_proxy_configured() or antigravity_config.is_user_proxy_env_set():
            self.smart_proxy.start()

        self.log("Приложение GeoHide Manager успешно запущено.")
        if is_admin():
            self.log("Режим Администратора активен.")
        else:
            self.log("Запущено в стандартном пользовательском режиме. Изолированный режим работает полностью без UAC.", level="INFO")

        self.trigger_status_check()
        self._schedule_auto_refresh()

    def _center_window(self, width: int, height: int):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _setup_icon(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        ico_path = os.path.join(base_dir, "icon.ico")
        png_path = os.path.join(base_dir, "icon.png")

        if os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass
        
        self.logo_image = None
        if os.path.exists(png_path):
            try:
                pil_img = Image.open(png_path)
                self.logo_image = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(48, 48))
            except Exception:
                pass

    def _create_widgets(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # ---------------- 1. Шапка (Header) ----------------
        self.header_frame = ctk.CTkFrame(self, corner_radius=12, fg_color=("#1f242c", "#161b22"))
        self.header_frame.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        self.header_frame.grid_columnconfigure(1, weight=1)

        if self.logo_image:
            self.logo_label = ctk.CTkLabel(self.header_frame, text="", image=self.logo_image)
            self.logo_label.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=12)

        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="GeoHide DNS Manager",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.title_label.grid(row=0, column=1, sticky="w", pady=(12, 0))

        self.subtitle_label = ctk.CTkLabel(
            self.header_frame,
            text="Обход блокировок Gemini для Antigravity 2.0, CLI (agy) и IDE",
            font=ctk.CTkFont(size=12),
            text_color="#8b949e"
        )
        self.subtitle_label.grid(row=1, column=1, sticky="w", pady=(0, 12))

        admin_text = "🛡️ Администратор" if is_admin() else "👤 Пользователь"
        admin_color = "#238636" if is_admin() else "#388bfd"
        self.admin_badge = ctk.CTkLabel(
            self.header_frame,
            text=admin_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ffffff",
            fg_color=admin_color,
            corner_radius=8,
            padx=10,
            pady=4
        )
        self.admin_badge.grid(row=0, column=2, rowspan=2, padx=16, pady=12, sticky="e")

        # ---------------- 2. Переключатель режима работы ----------------
        self.mode_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.mode_frame.grid(row=1, column=0, padx=16, pady=(2, 6), sticky="ew")
        self.mode_frame.grid_columnconfigure(0, weight=1)

        self.mode_selector = ctk.CTkSegmentedButton(
            self.mode_frame,
            values=["🎯 Только Antigravity (IDE, 2.0, agy CLI)", "🌐 Вся Windows (Глобальный)"],
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            command=self.on_mode_changed
        )
        self.mode_selector.set("🎯 Только Antigravity (IDE, 2.0, agy CLI)")
        self.mode_selector.grid(row=0, column=0, sticky="ew")

        # ---------------- 3. Карточка статуса ----------------
        self.status_card = ctk.CTkFrame(self, corner_radius=12, fg_color=("#262c36", "#1c2128"), border_width=2, border_color="#30363d")
        self.status_card.grid(row=2, column=0, padx=16, pady=6, sticky="ew")
        self.status_card.grid_columnconfigure((0, 1, 2), weight=1)

        self.status_indicator_frame = ctk.CTkFrame(self.status_card, fg_color="transparent")
        self.status_indicator_frame.grid(row=0, column=0, columnspan=3, padx=16, pady=(12, 6), sticky="ew")

        self.status_dot = ctk.CTkLabel(
            self.status_indicator_frame,
            text="●",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color="#8b949e"
        )
        self.status_dot.pack(side="left", padx=(4, 8))

        self.status_main_label = ctk.CTkLabel(
            self.status_indicator_frame,
            text="Инициализация...",
            font=ctk.CTkFont(size=17, weight="bold")
        )
        self.status_main_label.pack(side="left")

        self.status_time_label = ctk.CTkLabel(
            self.status_indicator_frame,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#8b949e"
        )
        self.status_time_label.pack(side="right", padx=6)

        self.tile1_title, self.tile1_val = self._create_info_tile(self.status_card, col=0, title="Smart Proxy", value="Опрос...", icon="🛡️")
        self.tile2_title, self.tile2_val = self._create_info_tile(self.status_card, col=1, title="IDE & CLI Config", value="Опрос...", icon="⚙️")
        self.tile3_title, self.tile3_val = self._create_info_tile(self.status_card, col=2, title="Процессы Antigravity", value="Опрос...", icon="⚡")

        # ---------------- 4. Кнопки управления ----------------
        self.actions_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.actions_frame.grid(row=3, column=0, padx=16, pady=6, sticky="ew")
        self.actions_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.btn_enable = ctk.CTkButton(
            self.actions_frame,
            text="✔  Включить для Antigravity",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#238636",
            hover_color="#2ea043",
            height=44,
            corner_radius=10,
            command=self.on_enable_clicked
        )
        self.btn_enable.grid(row=0, column=0, padx=6, pady=4, sticky="ew")

        self.btn_disable = ctk.CTkButton(
            self.actions_frame,
            text="✖  Отключить",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#b62324",
            hover_color="#da3633",
            height=44,
            corner_radius=10,
            command=self.on_disable_clicked
        )
        self.btn_disable.grid(row=0, column=1, padx=6, pady=4, sticky="ew")

        self.btn_refresh = ctk.CTkButton(
            self.actions_frame,
            text="🔄  Обновить статус",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#1f6feb",
            hover_color="#388bfd",
            height=44,
            corner_radius=10,
            command=self.trigger_status_check
        )
        self.btn_refresh.grid(row=0, column=2, padx=6, pady=4, sticky="ew")

        # ---------------- 5. Журнал событий ----------------
        self.log_frame = ctk.CTkFrame(self, corner_radius=12, fg_color=("#1f242c", "#161b22"))
        self.log_frame.grid(row=4, column=0, padx=16, pady=(6, 16), sticky="nsew")
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=1)

        self.log_header_frame = ctk.CTkFrame(self.log_frame, fg_color="transparent")
        self.log_header_frame.grid(row=0, column=0, padx=12, pady=(10, 6), sticky="ew")
        self.log_header_frame.grid_columnconfigure(0, weight=1)

        self.log_title = ctk.CTkLabel(
            self.log_header_frame,
            text="Журнал операций и сетевой трафик",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.log_title.grid(row=0, column=0, sticky="w")

        self.btn_clear_log = ctk.CTkButton(
            self.log_header_frame,
            text="Очистить",
            font=ctk.CTkFont(size=11),
            width=70,
            height=26,
            fg_color="#30363d",
            hover_color="#484f58",
            corner_radius=6,
            command=self.clear_logs
        )
        self.btn_clear_log.grid(row=0, column=1, sticky="e")

        self.log_box = ctk.CTkTextbox(
            self.log_frame,
            corner_radius=8,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=("#161a20", "#0d1117"),
            border_width=1,
            border_color="#30363d"
        )
        self.log_box.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")

    def _create_info_tile(self, parent, col: int, title: str, value: str, icon: str):
        tile = ctk.CTkFrame(parent, fg_color=("#1e232b", "#14181f"), corner_radius=10)
        tile.grid(row=1, column=col, padx=8, pady=(4, 12), sticky="nsew")

        lbl_title = ctk.CTkLabel(
            tile,
            text=f"{icon} {title}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#8b949e"
        )
        lbl_title.pack(anchor="w", padx=12, pady=(8, 2))

        lbl_val = ctk.CTkLabel(
            tile,
            text=value,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#c9d1d9"
        )
        lbl_val.pack(anchor="w", padx=12, pady=(0, 8))
        return lbl_title, lbl_val

    def on_mode_changed(self, value: str):
        if "Только Antigravity" in value:
            self.active_mode = "isolated"
            self.btn_enable.configure(text="✔  Включить для Antigravity")
            self.log("Режим: Изолированный (Antigravity IDE, 2.0 Desktop, agy CLI)")
        else:
            self.active_mode = "global"
            self.btn_enable.configure(text="✔  Включить для всей системы")
            self.log("Режим: Глобальный (Для всей Windows через DNS и hosts)")
        self.trigger_status_check()

    def log(self, message: str, level: str = "INFO"):
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        prefix = f"[{now_str}]"
        if level == "WARN":
            tag = " [ПРЕДУПРЕЖДЕНИЕ]"
        elif level == "ERR":
            tag = " [ОШИБКА]"
        elif level == "OK":
            tag = " [УСПЕХ]"
        elif level == "PROXY":
            tag = " [PROXY-TUNNEL]"
        else:
            tag = " [ИНФО]"

        full_line = f"{prefix}{tag} {message}\n"

        def _append():
            self.log_box.insert("end", full_line)
            self.log_box.see("end")

        self.after(0, _append)

    def clear_logs(self):
        self.log_box.delete("1.0", "end")

    def set_busy(self, busy: bool, action_name: str = ""):
        self.is_busy = busy
        state = "disabled" if busy else "normal"
        self.btn_enable.configure(state=state)
        self.btn_disable.configure(state=state)
        self.btn_refresh.configure(state=state)

        if busy:
            self.status_time_label.configure(text=f"Выполняется: {action_name}...")
        else:
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            self.status_time_label.configure(text=f"Обновлено: {now_str}")

    # ---------------- Логика включения / выключения ----------------
    def on_enable_clicked(self):
        if self.is_busy:
            return
        if self.active_mode == "isolated":
            threading.Thread(target=self._worker_enable_isolated, daemon=True).start()
        else:
            threading.Thread(target=self._worker_enable_global, daemon=True).start()

    def _worker_enable_isolated(self):
        self.set_busy(True, "Включение Smart Proxy")
        self.log("Запуск локального Smart Proxy...")
        
        # 1. Запуск прокси сервера
        proxy_ok = self.smart_proxy.start()
        if not proxy_ok:
            self.log("Ошибка запуска Smart Proxy!", level="ERR")
            self.set_busy(False)
            return

        # 2. Настройка Antigravity IDE, 2.0 и CLI
        self.log("Настройка Antigravity IDE (settings.json) и переменных среды для CLI (agy) / 2.0...")
        cfg_ok, cfg_msg = antigravity_config.enable_all_antigravity_proxies("http://127.0.0.1:8899")
        if cfg_ok:
            self.log(cfg_msg, level="OK")
        else:
            self.log(cfg_msg, level="WARN")

        # 3. Проверка: запущена ли Antigravity прямо сейчас
        is_running = antigravity_config.is_any_antigravity_running()
        self.set_busy(False)
        self._worker_check_status()

        if is_running:
            self.log("Обнаружена активная сессия Antigravity. Запрос подтверждения перезапуска...", level="WARN")
            # Открываем диалоговое окно в главном GUI потоке
            self.after(0, self._show_restart_dialog)
        else:
            self.log("Antigravity сейчас не запущена. При следующем запуске она сразу подключится через GeoHide.", level="OK")

    def _show_restart_dialog(self):
        """Отображает диалог предупреждения и перезапуска."""
        def on_restart():
            threading.Thread(target=self._do_restart_antigravity, daemon=True).start()

        def on_later():
            self.log("Пользователь выбрал отложить перезапуск. Настройки прокси вступят в силу после ручного перезапуска.", level="INFO")

        RestartConfirmDialog(self, on_restart=on_restart, on_later=on_later)

    def _do_restart_antigravity(self):
        self.log("Выполняется перезапуск Antigravity...")
        ok, msg = antigravity_config.restart_antigravity()
        if ok:
            self.log(msg, level="OK")
        else:
            self.log(msg, level="ERR")
        self._worker_check_status()

    def _worker_enable_global(self):
        self.set_busy(True, "Включение глобального GeoHide")
        self.log("Запущен процесс глобальной активации GeoHide...")
        success, message = geohide_core.enable_geohide(log_callback=self.log)
        if success:
            self.log(message, level="OK")
        else:
            self.log(message, level="ERR")
        self.set_busy(False)
        self._worker_check_status()

    def on_disable_clicked(self):
        if self.is_busy:
            return
        if self.active_mode == "isolated":
            threading.Thread(target=self._worker_disable_isolated, daemon=True).start()
        else:
            threading.Thread(target=self._worker_disable_global, daemon=True).start()

    def _worker_disable_isolated(self):
        self.set_busy(True, "Отключение Smart Proxy")
        self.log("Остановка Smart Proxy и очистка конфигураций...")
        self.smart_proxy.stop()
        cfg_ok, cfg_msg = antigravity_config.disable_all_antigravity_proxies()
        if cfg_ok:
            self.log(cfg_msg, level="OK")
        else:
            self.log(cfg_msg, level="ERR")
        self.set_busy(False)
        self._worker_check_status()

    def _worker_disable_global(self):
        self.set_busy(True, "Отключение глобального GeoHide")
        self.log("Запущен процесс отключения глобального GeoHide...")
        success, message = geohide_core.disable_geohide(log_callback=self.log)
        if success:
            self.log(message, level="OK")
        else:
            self.log(message, level="ERR")
        self.set_busy(False)
        self._worker_check_status()

    def trigger_status_check(self):
        if self.is_busy:
            return
        threading.Thread(target=self._worker_check_status, daemon=True).start()

    def _schedule_auto_refresh(self):
        if self.auto_refresh_enabled and not self.is_busy:
            self.trigger_status_check()
        self.after(12000, self._schedule_auto_refresh)

    def _worker_check_status(self):
        if self.active_mode == "isolated":
            self._check_status_isolated()
        else:
            self._check_status_global()

    def _check_status_isolated(self):
        proxy_running = self.smart_proxy.is_running
        antigravity_configured = antigravity_config.is_antigravity_proxy_configured()
        env_configured = antigravity_config.is_user_proxy_env_set()
        procs = antigravity_config.get_target_processes_status()

        def _update_ui():
            self.tile1_title.configure(text="🛡️ Smart Proxy")
            self.tile2_title.configure(text="⚙️ IDE & CLI Config")
            self.tile3_title.configure(text="⚡ Процессы Antigravity")

            is_active = proxy_running and (antigravity_configured or env_configured)

            if is_active:
                self.status_dot.configure(text_color="#3fb950")
                self.status_main_label.configure(
                    text="Smart Proxy АКТИВЕН (IDE, 2.0, agy CLI)",
                    text_color="#3fb950"
                )
                self.status_card.configure(border_color="#238636")
            elif not proxy_running and not antigravity_configured and not env_configured:
                self.status_dot.configure(text_color="#8b949e")
                self.status_main_label.configure(
                    text="Smart Proxy ОТКЛЮЧЕН (Прямое подключение)",
                    text_color="#8b949e"
                )
                self.status_card.configure(border_color="#30363d")
            else:
                self.status_dot.configure(text_color="#d29922")
                self.status_main_label.configure(
                    text="Частично: Прокси или конфигурация рассинхронизированы",
                    text_color="#d29922"
                )
                self.status_card.configure(border_color="#9e6a03")

            if proxy_running:
                self.tile1_val.configure(text="127.0.0.1:8899 (Работает)", text_color="#3fb950")
            else:
                self.tile1_val.configure(text="Остановлен", text_color="#8b949e")

            cfg_status = []
            if antigravity_configured:
                cfg_status.append("IDE")
            if env_configured:
                cfg_status.append("CLI / 2.0")
            
            if cfg_status:
                self.tile2_val.configure(text=f"Включен ({' + '.join(cfg_status)})", text_color="#3fb950")
            else:
                self.tile2_val.configure(text="Отключен (Прямое)", text_color="#8b949e")

            ls_pids = procs.get("language_server", [])
            ag_pids = procs.get("antigravity", [])
            agy_pids = procs.get("agy", [])
            
            summary_parts = []
            if ag_pids:
                summary_parts.append(f"IDE: {len(ag_pids)}")
            if ls_pids:
                summary_parts.append(f"LS: {ls_pids[0]}")
            if agy_pids:
                summary_parts.append(f"CLI: {len(agy_pids)}")

            if summary_parts:
                self.tile3_val.configure(text=" | ".join(summary_parts), text_color="#3fb950")
            else:
                self.tile3_val.configure(text="Не запущены", text_color="#8b949e")

            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            self.status_time_label.configure(text=f"Обновлено: {now_str}")

        self.after(0, _update_ui)

    def _check_status_global(self):
        status = geohide_core.get_current_status()
        ping_ok, ping_msg = geohide_core.ping_host("gemini.google.com")

        def _update_ui():
            self.tile1_title.configure(text="🌐 DNS Серверы")
            self.tile2_title.configure(text="📝 Файл Hosts")
            self.tile3_title.configure(text="⚡ Пинг Gemini")

            state = status["state"]
            hosts = status["hosts"]
            gh_adapters_count = status["geohide_adapters_count"]
            total_adapters = status["total_adapters_count"]

            if state == "active":
                self.status_dot.configure(text_color="#3fb950")
                self.status_main_label.configure(
                    text="Глобальный GeoHide АКТИВЕН (Вся Windows)",
                    text_color="#3fb950"
                )
                self.status_card.configure(border_color="#238636")
            elif state == "inactive":
                self.status_dot.configure(text_color="#f85149")
                self.status_main_label.configure(
                    text="Глобальный GeoHide ОТКЛЮЧЕН",
                    text_color="#f85149"
                )
                self.status_card.configure(border_color="#30363d")
            else:
                self.status_dot.configure(text_color="#d29922")
                self.status_main_label.configure(
                    text="Глобальный GeoHide ЧАСТИЧНО АКТИВЕН",
                    text_color="#d29922"
                )
                self.status_card.configure(border_color="#9e6a03")

            if gh_adapters_count > 0:
                self.tile1_val.configure(
                    text=f"GeoHide ({gh_adapters_count}/{total_adapters} адапт.)",
                    text_color="#3fb950"
                )
            else:
                self.tile1_val.configure(
                    text="Стандартный (DHCP)",
                    text_color="#8b949e"
                )

            if hosts.get("has_geohide"):
                cnt = hosts.get("count", 0)
                date_str = f" ({hosts['date']})" if hosts.get("date") else ""
                self.tile2_val.configure(
                    text=f"{cnt} записей{date_str}",
                    text_color="#3fb950"
                )
            else:
                self.tile2_val.configure(
                    text="Записи отсутствуют",
                    text_color="#8b949e"
                )

            if ping_ok:
                self.tile3_val.configure(
                    text=f"{ping_msg} (Доступен)",
                    text_color="#3fb950"
                )
            else:
                self.tile3_val.configure(
                    text=f"{ping_msg}",
                    text_color="#f85149"
                )

            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            self.status_time_label.configure(text=f"Обновлено: {now_str}")

        self.after(0, _update_ui)

    def on_closing(self):
        if self.smart_proxy and self.smart_proxy.is_running:
            self.smart_proxy.stop()
        self.destroy()


if __name__ == "__main__":
    elevate_if_needed()

    app = GeoHideApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
