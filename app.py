"""
GeoHide DNS Manager - Graphical User Interface v1.4.0
Поддерживает:
1. 🎯 Изолированный режим (Antigravity IDE, 2.0 Desktop и agy CLI)
2. 🌐 Глобальный режим (Для всей Windows)
3. 🔓 Разблокировка аккаунтов (Вход с любого Google аккаунта, снятие ineligible / 400)
4. 📌 Работа в системном трее (pystray) при закрытии крестиком
5. 🚀 Автозапуск вместе с Windows через реестр
6. 🛡️ Предупреждение и подтверждение перед перезапуском
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
import pystray
from pystray import MenuItem as item

# Внутренние модули
import geohide_core
import antigravity_config
import autostart
import account_patcher
from local_proxy import GeoHideSmartProxy


def get_resource_path(relative_path: str) -> str:
    """Возвращает корректный путь к ресурсам как для скрипта, так и для скомпилированного .exe."""
    if getattr(sys, "frozen", False):
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    direct_path = os.path.join(base_path, relative_path)
    if os.path.exists(direct_path):
        return direct_path
    
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    return os.path.join(exe_dir, relative_path)


# Проверка прав администратора и автоматическое повышение (UAC)
def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def elevate_if_needed():
    if sys.platform == "win32" and not is_admin():
        target = sys.executable if getattr(sys, "frozen", False) else sys.executable
        params = "" if getattr(sys, "frozen", False) else f'"{os.path.abspath(__file__)}"'
        extra_args = " ".join(f'"{arg}"' for arg in sys.argv[1:])
        if extra_args:
            params = f"{params} {extra_args}".strip()

        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", target, params, None, 1)
        if ret > 32:
            sys.exit(0)
        else:
            print("Предупреждение: Запуск без прав администратора. Изолированный режим работает без ограничений.")


# Настройка темы CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class CustomConfirmDialog(ctk.CTkToplevel):
    """Универсальное модальное диалоговое окно для подтверждения действий."""
    def __init__(self, parent, title: str, header: str, desc: str, confirm_text: str, cancel_text: str, on_confirm, on_cancel=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("540x260")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        parent.update_idletasks()
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw - 540) // 2
        y = py + (ph - 260) // 2
        self.geometry(f"540x260+{max(0, x)}+{max(0, y)}")

        self.on_confirm = on_confirm
        self.on_cancel = on_cancel

        self._create_widgets(header, desc, confirm_text, cancel_text)

    def _create_widgets(self, header: str, desc: str, confirm_text: str, cancel_text: str):
        self.grid_columnconfigure(0, weight=1)

        frame = ctk.CTkFrame(self, corner_radius=12, fg_color=("#1f242c", "#161b22"))
        frame.pack(fill="both", expand=True, padx=16, pady=16)

        header_label = ctk.CTkLabel(
            frame,
            text=header,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f85149"
        )
        header_label.pack(anchor="w", padx=20, pady=(16, 8))

        desc_label = ctk.CTkLabel(
            frame,
            text=desc,
            font=ctk.CTkFont(size=12),
            text_color="#c9d1d9",
            justify="left"
        )
        desc_label.pack(anchor="w", padx=20, pady=(0, 16))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 16))
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        btn_yes = ctk.CTkButton(
            btn_frame,
            text=confirm_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#238636",
            hover_color="#2ea043",
            height=38,
            corner_radius=8,
            command=self._handle_confirm
        )
        btn_yes.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        btn_no = ctk.CTkButton(
            btn_frame,
            text=cancel_text,
            font=ctk.CTkFont(size=13),
            fg_color="#30363d",
            hover_color="#484f58",
            height=38,
            corner_radius=8,
            command=self._handle_cancel
        )
        btn_no.grid(row=0, column=1, padx=(8, 0), sticky="ew")

    def _handle_confirm(self):
        self.destroy()
        if self.on_confirm:
            self.on_confirm()

    def _handle_cancel(self):
        self.destroy()
        if self.on_cancel:
            self.on_cancel()


class GeoHideApp(ctk.CTk):
    def __init__(self, start_minimized: bool = False):
        super().__init__()

        self.title("GeoHide DNS Manager")
        self.geometry("780x800")
        self.minsize(720, 720)

        self._center_window(780, 800)
        self._setup_icon()

        self.is_busy = False
        self.auto_refresh_enabled = True
        self.active_mode = "isolated"
        self.is_exiting = False

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

        # Настройка системного трея
        self._setup_tray()

        # Протокол перехвата кнопки закрытия [X] -> сворачивание в трей
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        self.log("Приложение GeoHide Manager успешно запущено.")
        if is_admin():
            self.log("Режим Администратора активен.")
        else:
            self.log("Запущено в стандартном пользовательском режиме. Изолированный режим работает без ограничений.")

        if autostart.is_autostart_enabled():
            self.log("Автозапуск с Windows: Включен.")

        self.trigger_status_check()
        self._schedule_auto_refresh()

        if start_minimized:
            self.withdraw()
            self.log("Приложение запущено в свернутом виде (в системном трее).")

    def _center_window(self, width: int, height: int):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _setup_icon(self):
        ico_path = get_resource_path("icon.ico")
        png_path = get_resource_path("icon.png")

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
                self.pil_icon = pil_img
            except Exception:
                self.pil_icon = None
        else:
            self.pil_icon = None

    def _setup_tray(self):
        if not self.pil_icon:
            self.pil_icon = Image.new("RGBA", (64, 64), color="#238636")

        menu = pystray.Menu(
            item("Открыть окно", self.show_window, default=True),
            item(
                "Включить прокси",
                lambda: self.after(0, self.on_enable_clicked),
                visible=lambda item: not self.smart_proxy.is_running
            ),
            item(
                "Отключить прокси",
                lambda: self.after(0, self.on_disable_clicked),
                visible=lambda item: self.smart_proxy.is_running
            ),
            pystray.Menu.SEPARATOR,
            item(
                "Автозапуск с Windows",
                self._toggle_autostart_tray,
                checked=lambda item: autostart.is_autostart_enabled()
            ),
            pystray.Menu.SEPARATOR,
            item("Выход", self.exit_application)
        )

        self.tray_icon = pystray.Icon("GeoHideManager", self.pil_icon, "GeoHide DNS Manager", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self, icon=None, item=None):
        def _show():
            self.deiconify()
            self.lift()
            self.focus_force()
        self.after(0, _show)

    def minimize_to_tray(self):
        self.withdraw()
        self.log("Окно свернуто в системный трей возле часов Windows.")

    def exit_application(self, icon=None, item=None):
        self.is_exiting = True
        if self.smart_proxy and self.smart_proxy.is_running:
            self.smart_proxy.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.after(0, self.destroy)

    def _toggle_autostart_tray(self, icon=None, item=None):
        current = autostart.is_autostart_enabled()
        autostart.set_autostart(not current)
        self.after(0, self._update_autostart_ui)

    def _on_autostart_switch_changed(self):
        is_on = self.autostart_switch.get() == 1
        autostart.set_autostart(is_on)
        state_str = "включен" if is_on else "отключен"
        self.log(f"Автозапуск с Windows {state_str}.")

    def _update_autostart_ui(self):
        is_on = autostart.is_autostart_enabled()
        if hasattr(self, "autostart_switch"):
            if is_on:
                self.autostart_switch.select()
            else:
                self.autostart_switch.deselect()

    def _create_widgets(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

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
            text="Обход блокировок Gemini и снятие ограничений Google для Antigravity",
            font=ctk.CTkFont(size=12),
            text_color="#8b949e"
        )
        self.subtitle_label.grid(row=1, column=1, sticky="w", pady=(0, 12))

        self.header_right = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.header_right.grid(row=0, column=2, rowspan=2, padx=16, pady=12, sticky="e")

        self.autostart_switch = ctk.CTkSwitch(
            self.header_right,
            text="Автозапуск",
            font=ctk.CTkFont(size=11),
            command=self._on_autostart_switch_changed
        )
        if autostart.is_autostart_enabled():
            self.autostart_switch.select()
        self.autostart_switch.pack(side="top", anchor="e", pady=(0, 6))

        admin_text = "🛡️ Администратор" if is_admin() else "👤 Пользователь"
        admin_color = "#238636" if is_admin() else "#388bfd"
        self.admin_badge = ctk.CTkLabel(
            self.header_right,
            text=admin_text,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#ffffff",
            fg_color=admin_color,
            corner_radius=6,
            padx=8,
            pady=2
        )
        self.admin_badge.pack(side="bottom", anchor="e")

        # ---------------- 2. Переключатель режима ----------------
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

        # ---------------- 3. Карточка сетевого статуса ----------------
        self.status_card = ctk.CTkFrame(self, corner_radius=12, fg_color=("#262c36", "#1c2128"), border_width=2, border_color="#30363d")
        self.status_card.grid(row=2, column=0, padx=16, pady=4, sticky="ew")
        self.status_card.grid_columnconfigure((0, 1, 2), weight=1)

        self.status_indicator_frame = ctk.CTkFrame(self.status_card, fg_color="transparent")
        self.status_indicator_frame.grid(row=0, column=0, columnspan=3, padx=16, pady=(10, 4), sticky="ew")

        self.status_dot = ctk.CTkLabel(
            self.status_indicator_frame,
            text="●",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#8b949e"
        )
        self.status_dot.pack(side="left", padx=(4, 8))

        self.status_main_label = ctk.CTkLabel(
            self.status_indicator_frame,
            text="Инициализация...",
            font=ctk.CTkFont(size=16, weight="bold")
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
        self.tile3_title, self.tile3_val = self._create_info_tile(self.status_card, col=2, title="Процессы", value="Опрос...", icon="⚡")

        # ---------------- 4. Карточка разблокировки аккаунтов (Account Unlock) ----------------
        self.account_card = ctk.CTkFrame(self, corner_radius=12, fg_color=("#202630", "#181d24"), border_width=1, border_color="#30363d")
        self.account_card.grid(row=3, column=0, padx=16, pady=6, sticky="ew")
        self.account_card.grid_columnconfigure(0, weight=1)
        self.account_card.grid_columnconfigure(1, weight=0)

        self.acc_header_frame = ctk.CTkFrame(self.account_card, fg_color="transparent")
        self.acc_header_frame.grid(row=0, column=0, padx=14, pady=(10, 2), sticky="w")

        self.acc_title = ctk.CTkLabel(
            self.acc_header_frame,
            text="🔓 Вход с любого Google аккаунта (Снятие ошибки 400 / ineligible)",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.acc_title.pack(anchor="w")

        self.acc_status_label = ctk.CTkLabel(
            self.account_card,
            text="Статус: Опрос компонентов...",
            font=ctk.CTkFont(size=12),
            text_color="#8b949e"
        )
        self.acc_status_label.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="w")

        self.acc_btn_frame = ctk.CTkFrame(self.account_card, fg_color="transparent")
        self.acc_btn_frame.grid(row=0, column=1, rowspan=2, padx=14, pady=10, sticky="e")

        self.btn_patch_acc = ctk.CTkButton(
            self.acc_btn_frame,
            text="🔓 Разблокировать",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1f6feb",
            hover_color="#388bfd",
            width=135,
            height=32,
            corner_radius=8,
            command=self.on_patch_accounts_clicked
        )
        self.btn_patch_acc.pack(side="left", padx=4)

        self.btn_unpatch_acc = ctk.CTkButton(
            self.acc_btn_frame,
            text="Откат",
            font=ctk.CTkFont(size=12),
            fg_color="#30363d",
            hover_color="#484f58",
            width=70,
            height=32,
            corner_radius=8,
            command=self.on_unpatch_accounts_clicked
        )
        self.btn_unpatch_acc.pack(side="left", padx=4)

        # ---------------- 5. Кнопки управления сетью ----------------
        self.actions_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.actions_frame.grid(row=4, column=0, padx=16, pady=4, sticky="ew")
        self.actions_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.btn_enable = ctk.CTkButton(
            self.actions_frame,
            text="✔  Включить для Antigravity",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#238636",
            hover_color="#2ea043",
            height=42,
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
            height=42,
            corner_radius=10,
            command=self.on_disable_clicked
        )
        self.btn_disable.grid(row=0, column=1, padx=6, pady=4, sticky="ew")

        self.btn_refresh = ctk.CTkButton(
            self.actions_frame,
            text="🔄  Обновить статус",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#30363d",
            hover_color="#484f58",
            height=42,
            corner_radius=10,
            command=self.trigger_status_check
        )
        self.btn_refresh.grid(row=0, column=2, padx=6, pady=4, sticky="ew")

        # ---------------- 6. Журнал событий ----------------
        self.log_frame = ctk.CTkFrame(self, corner_radius=12, fg_color=("#1f242c", "#161b22"))
        self.log_frame.grid(row=5, column=0, padx=16, pady=(6, 16), sticky="nsew")
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=1)

        self.log_header_frame = ctk.CTkFrame(self.log_frame, fg_color="transparent")
        self.log_header_frame.grid(row=0, column=0, padx=12, pady=(8, 4), sticky="ew")
        self.log_header_frame.grid_columnconfigure(0, weight=1)

        self.log_title = ctk.CTkLabel(
            self.log_header_frame,
            text="Журнал операций и сетевой трафик",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.log_title.grid(row=0, column=0, sticky="w")

        self.btn_clear_log = ctk.CTkButton(
            self.log_header_frame,
            text="Очистить",
            font=ctk.CTkFont(size=11),
            width=70,
            height=24,
            fg_color="#30363d",
            hover_color="#484f58",
            corner_radius=6,
            command=self.clear_logs
        )
        self.btn_clear_log.grid(row=0, column=1, sticky="e")

        self.log_box = ctk.CTkTextbox(
            self.log_frame,
            corner_radius=8,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=("#161a20", "#0d1117"),
            border_width=1,
            border_color="#30363d"
        )
        self.log_box.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="nsew")

    def _create_info_tile(self, parent, col: int, title: str, value: str, icon: str):
        tile = ctk.CTkFrame(parent, fg_color=("#1e232b", "#14181f"), corner_radius=10)
        tile.grid(row=1, column=col, padx=8, pady=(4, 10), sticky="nsew")

        lbl_title = ctk.CTkLabel(
            tile,
            text=f"{icon} {title}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#8b949e"
        )
        lbl_title.pack(anchor="w", padx=10, pady=(6, 2))

        lbl_val = ctk.CTkLabel(
            tile,
            text=value,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#c9d1d9"
        )
        lbl_val.pack(anchor="w", padx=10, pady=(0, 6))
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
            if hasattr(self, "log_box") and self.log_box.winfo_exists():
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
        self.btn_patch_acc.configure(state=state)
        self.btn_unpatch_acc.configure(state=state)

        if busy:
            self.status_time_label.configure(text=f"Выполняется: {action_name}...")
        else:
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            self.status_time_label.configure(text=f"Обновлено: {now_str}")

    # ---------------- Разблокировка аккаунтов (Patching) ----------------
    def on_patch_accounts_clicked(self):
        if self.is_busy:
            return
        threading.Thread(target=self._worker_patch_accounts, daemon=True).start()

    def _worker_patch_accounts(self):
        self.set_busy(True, "Разблокировка аккаунтов")
        self.log("Проверка возможности разблокировки бинарников Antigravity...")

        # Проверяем, запущен ли language_server прямо сейчас
        is_running = antigravity_config.is_any_antigravity_running()
        if is_running:
            self.log("Antigravity сейчас запущена. Для применения патча требуется подтверждение пользователя.", level="WARN")
            self.set_busy(False)
            
            def _prompt():
                CustomConfirmDialog(
                    self,
                    title="Разблокировка аккаунтов",
                    header="⚠️  Antigravity сейчас запущена",
                    desc=(
                        "Файл language_server.exe сейчас занят запущенным процессом Antigravity.\n"
                        "Для применения разблокировки Antigravity будет кратковременно закрыта\n"
                        "и перезапущена.\n\n"
                        "Выполнить закрытие и разблокировать прямо сейчас?"
                    ),
                    confirm_text="🚀 Закрыть и разблокировать",
                    cancel_text="⏱️ Отмена",
                    on_confirm=lambda: threading.Thread(target=self._execute_patch_force, daemon=True).start(),
                    on_cancel=lambda: self.log("Разблокировка отменена пользователем. Закройте Antigravity вручную и повторите попытку.", level="INFO")
                )
            self.after(0, _prompt)
            return

        # Если Antigravity не запущена, применяем патч сразу и чисто
        ok, msg = account_patcher.patch_all(force_kill=False)
        if ok:
            self.log(msg, level="OK")
        else:
            self.log(msg, level="ERR")
        self.set_busy(False)
        self._worker_check_status()

    def _execute_patch_force(self):
        self.set_busy(True, "Разблокировка (с перезапуском)")
        self.log("Применение патча к бинарникам Antigravity...")
        ok, msg = account_patcher.patch_all(force_kill=True)
        if ok:
            self.log(msg, level="OK")
            self.log("Перезапуск Antigravity с новыми параметрами...")
            antigravity_config.restart_antigravity()
        else:
            self.log(msg, level="ERR")
        self.set_busy(False)
        self._worker_check_status()

    def on_unpatch_accounts_clicked(self):
        if self.is_busy:
            return
        threading.Thread(target=self._worker_unpatch_accounts, daemon=True).start()

    def _worker_unpatch_accounts(self):
        self.set_busy(True, "Откат разблокировки")
        self.log("Восстановление оригинальных бинарников Antigravity...")
        is_running = antigravity_config.is_any_antigravity_running()
        if is_running:
            self.log("Внимание: Antigravity запущена. Файлы могут быть заблокированы.", level="WARN")

        ok, msg = account_patcher.unpatch_all(force_kill=False)
        self.log(f"Результат отката: {msg}", level="OK" if ok else "WARN")
        self.set_busy(False)
        self._worker_check_status()

    # ---------------- Включение / выключение сети ----------------
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
        
        proxy_ok = self.smart_proxy.start()
        if not proxy_ok:
            self.log("Ошибка запуска Smart Proxy!", level="ERR")
            self.set_busy(False)
            return

        self.log("Настройка Antigravity IDE (settings.json) и переменных среды для CLI (agy) / 2.0...")
        cfg_ok, cfg_msg = antigravity_config.enable_all_antigravity_proxies("http://127.0.0.1:8899")
        if cfg_ok:
            self.log(cfg_msg, level="OK")
        else:
            self.log(cfg_msg, level="WARN")

        is_running = antigravity_config.is_any_antigravity_running()
        self.set_busy(False)
        self._worker_check_status()

        if is_running:
            self.log("Обнаружена активная сессия Antigravity. Запрос подтверждения перезапуска...", level="WARN")
            self.after(0, self._show_restart_dialog)
        else:
            self.log("Antigravity сейчас не запущена. При следующем запуске она сразу подключится через GeoHide.", level="OK")

    def _show_restart_dialog(self):
        CustomConfirmDialog(
            self,
            title="Перезапуск Antigravity",
            header="⚠️  Antigravity (Gemini) сейчас запущена",
            desc=(
                "Для того чтобы Antigravity IDE, language_server и Antigravity 2.0 CLI (agy)\n"
                "применили новые настройки прокси и восстановили доступ к Gemini, необходимо\n"
                "перезапустить приложение.\n\n"
                "Перезапустить Antigravity прямо сейчас?"
            ),
            confirm_text="🚀 Перезапустить сейчас",
            cancel_text="⏱️ Перезапустить позже",
            on_confirm=lambda: threading.Thread(target=self._do_restart_antigravity, daemon=True).start(),
            on_cancel=lambda: self.log("Перезапуск отложен. Настройки прокси вступят в силу после ручного перезапуска.", level="INFO")
        )

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
        patch_info = account_patcher.get_overall_patch_status()
        if self.active_mode == "isolated":
            self._check_status_isolated(patch_info)
        else:
            self._check_status_global(patch_info)

    def _update_patch_ui(self, patch_info):
        st = patch_info.get("status")
        tot = patch_info.get("total", 0)
        patched = patch_info.get("patched", 0)

        if st == "fully_patched":
            self.acc_status_label.configure(
                text=f"Статус: 🟢 Все аккаунты разрешены ({patched}/{tot} файлов разблокировано)",
                text_color="#3fb950"
            )
            self.btn_patch_acc.configure(text="✔ Разблокировано", fg_color="#238636")
        elif st == "partially_patched":
            self.acc_status_label.configure(
                text=f"Статус: 🟡 Частично ({patched}/{tot} файлов разблокировано)",
                text_color="#d29922"
            )
            self.btn_patch_acc.configure(text="🔓 Разблокировать", fg_color="#1f6feb")
        else:
            self.acc_status_label.configure(
                text=f"Статус: ⚪ Стандартный (Только разрешенные регионы, {tot} компонентов)",
                text_color="#8b949e"
            )
            self.btn_patch_acc.configure(text="🔓 Разблокировать", fg_color="#1f6feb")

    def _check_status_isolated(self, patch_info):
        proxy_running = self.smart_proxy.is_running
        antigravity_configured = antigravity_config.is_antigravity_proxy_configured()
        env_configured = antigravity_config.is_user_proxy_env_set()
        procs = antigravity_config.get_target_processes_status()

        def _update_ui():
            if not self.winfo_exists():
                return

            self._update_patch_ui(patch_info)

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

    def _check_status_global(self, patch_info):
        status = geohide_core.get_current_status()
        ping_ok, ping_msg = geohide_core.ping_host("gemini.google.com")

        def _update_ui():
            if not self.winfo_exists():
                return

            self._update_patch_ui(patch_info)

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


if __name__ == "__main__":
    elevate_if_needed()

    start_min = "--minimized" in sys.argv or "--tray" in sys.argv
    app = GeoHideApp(start_minimized=start_min)
    app.mainloop()
