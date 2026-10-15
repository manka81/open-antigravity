"""
Antigravity Config & Process Management Module
Управление настройками прокси для Antigravity IDE, Antigravity 2.0 и CLI (agy),
а также мониторинг и перезапуск процессов с динамическим определением путей.
"""

import os
import sys
import json
import shutil
import winreg
import ctypes
import subprocess
import time
from typing import Optional

def get_antigravity_exe_path() -> str:
    """Динамически находит путь к Antigravity.exe на любой системе."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(local_app_data, "Programs", "antigravity", "Antigravity.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Antigravity", "Antigravity.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), "Antigravity", "Antigravity.exe"),
        shutil.which("Antigravity.exe") or ""
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return candidates[0]

def get_antigravity_settings_path() -> Optional[str]:
    """Возвращает путь к settings.json Antigravity IDE (%APPDATA%\\Antigravity\\User\\settings.json)."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return os.path.join(appdata, "Antigravity", "User", "settings.json")

def get_cli_settings_path() -> Optional[str]:
    """Возвращает путь к settings.json Antigravity CLI (~/.gemini/antigravity-cli/settings.json)."""
    user_home = os.path.expanduser("~")
    path = os.path.join(user_home, ".gemini", "antigravity-cli", "settings.json")
    return path if os.path.exists(path) else None

# ---------------- Переменные среды пользователя (User Environment) ----------------

def broadcast_env_change():
    """Оповещает Windows об изменении переменных среды (WM_SETTINGCHANGE)."""
    try:
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 1000, ctypes.byref(result)
        )
    except Exception:
        pass

def set_user_proxy_env(proxy_url: str = "http://127.0.0.1:8899") -> bool:
    """
    Устанавливает переменные среды пользователя (HKCU\\Environment)
    HTTP_PROXY, HTTPS_PROXY, ALL_PROXY, http_proxy, https_proxy.
    Это обеспечивает автоматическую работу agy CLI и Antigravity 2.0.
    """
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_SET_VALUE)
        for var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"]:
            winreg.SetValueEx(key, var, 0, winreg.REG_SZ, proxy_url)
            os.environ[var] = proxy_url
        winreg.CloseKey(key)
        broadcast_env_change()
        return True
    except Exception:
        return False

def clear_user_proxy_env() -> bool:
    """Удаляет переменные среды прокси из HKCU\\Environment."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_SET_VALUE)
        for var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"]:
            try:
                winreg.DeleteValue(key, var)
            except FileNotFoundError:
                pass
            if var in os.environ:
                del os.environ[var]
        winreg.CloseKey(key)
        broadcast_env_change()
        return True
    except Exception:
        return False

def is_user_proxy_env_set(proxy_url: str = "http://127.0.0.1:8899") -> bool:
    """Проверяет, установлены ли переменные среды прокси в реестре пользователя."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, "HTTP_PROXY")
        winreg.CloseKey(key)
        return val == proxy_url
    except Exception:
        return False

# ---------------- Настройки Antigravity IDE (settings.json) ----------------

def is_antigravity_proxy_configured(proxy_url: str = "http://127.0.0.1:8899") -> bool:
    """Проверяет, включен ли сейчас прокси в Antigravity IDE."""
    path = get_antigravity_settings_path()
    if not path or not os.path.exists(path):
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("http.proxy") == proxy_url
    except Exception:
        return False

def enable_all_antigravity_proxies(proxy_url: str = "http://127.0.0.1:8899") -> tuple[bool, str]:
    """
    Включает прокси для:
    1. Antigravity IDE (settings.json)
    2. Antigravity 2.0 и agy CLI (User Environment Variables)
    """
    errors = []

    # 1. Antigravity IDE
    ide_path = get_antigravity_settings_path()
    if ide_path:
        try:
            os.makedirs(os.path.dirname(ide_path), exist_ok=True)
            data = {}
            if os.path.exists(ide_path):
                try:
                    with open(ide_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    shutil.copyfile(ide_path, ide_path + ".bak")
                    data = {}

            data["http.proxy"] = proxy_url
            data["http.proxySupport"] = "on"
            data["http.proxyStrictSSL"] = False

            with open(ide_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            errors.append(f"IDE settings: {e}")

    # 2. CLI & Antigravity 2.0 (User Env)
    if not set_user_proxy_env(proxy_url):
        errors.append("Не удалось записать переменные окружения пользователя")

    if errors:
        return False, "; ".join(errors)
    return True, "Прокси успешно активирован для Antigravity IDE, Antigravity 2.0 и CLI (agy)!"

def disable_all_antigravity_proxies() -> tuple[bool, str]:
    """Отключает прокси для Antigravity IDE и удаляет переменные среды."""
    errors = []

    # 1. IDE settings
    ide_path = get_antigravity_settings_path()
    if ide_path and os.path.exists(ide_path):
        try:
            with open(ide_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            changed = False
            for k in ["http.proxy", "http.proxySupport", "http.proxyStrictSSL"]:
                if k in data:
                    del data[k]
                    changed = True
            if changed:
                with open(ide_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            errors.append(f"IDE settings: {e}")

    # 2. Clear User Env
    if not clear_user_proxy_env():
        errors.append("Не удалось очистить переменные окружения")

    if errors:
        return False, "; ".join(errors)
    return True, "Прокси успешно отключен для всех компонентов Antigravity."

# ---------------- Процессы и Перезапуск ----------------

def get_target_processes_status() -> dict:
    """
    Проверяет, запущены ли целевые процессы:
    Antigravity.exe, language_server.exe и agy.exe.
    """
    status = {"antigravity": [], "language_server": [], "agy": []}
    try:
        cmd = "wmic process get processid,name"
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[-1].isdigit():
                pid = int(parts[-1])
                name = parts[0].lower()
                if "antigravity" in name:
                    status["antigravity"].append(pid)
                elif "language_server" in name:
                    status["language_server"].append(pid)
                elif "agy" in name:
                    status["agy"].append(pid)
    except Exception:
        pass
    return status

def is_any_antigravity_running() -> bool:
    """Проверяет, запущен ли в данный момент Antigravity или language_server."""
    procs = get_target_processes_status()
    return len(procs["antigravity"]) > 0 or len(procs["language_server"]) > 0

def restart_antigravity() -> tuple[bool, str]:
    """
    Принудительно закрывает процессы Antigravity и language_server
    и перезапускает Antigravity.exe с новым окружением.
    """
    exe_path = get_antigravity_exe_path()
    if not os.path.exists(exe_path):
        return False, f"Файл {exe_path} не найден!"

    # 1. Завершаем процессы
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "Antigravity.exe", "/IM", "language_server.exe"],
            capture_output=True,
            text=True,
            creationflags=0x08000000
        )
    except Exception:
        pass

    # 2. Небольшая пауза для освобождения файлов
    time.sleep(1.5)

    # 3. Запускаем Antigravity заново
    try:
        env = os.environ.copy()
        env["HTTP_PROXY"] = "http://127.0.0.1:8899"
        env["HTTPS_PROXY"] = "http://127.0.0.1:8899"
        env["ALL_PROXY"] = "http://127.0.0.1:8899"

        subprocess.Popen(
            [exe_path],
            env=env,
            creationflags=0x00000008 | 0x00000200 # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        )
        return True, "Antigravity успешно перезапущена!"
    except Exception as e:
        return False, f"Ошибка запуска Antigravity: {e}"
