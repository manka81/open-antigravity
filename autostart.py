"""
Autostart Module
Управление автозапуском приложения через системный реестр Windows
HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
"""

import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "GeoHideManager"

def get_launch_command() -> str:
    """Возвращает строку запуска приложения в фоновом/минимизированном режиме."""
    if getattr(sys, "frozen", False):
        # Скомпилированный .exe
        exe_path = os.path.abspath(sys.executable)
        return f'"{exe_path}" --minimized'
    else:
        # Python скрипт
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "app.py"))
        py_exe = os.path.abspath(sys.executable)
        # Если есть pythonw.exe, используем его для предотвращения мигания консоли
        pyw_exe = py_exe.replace("python.exe", "pythonw.exe")
        runner = pyw_exe if os.path.exists(pyw_exe) else py_exe
        return f'"{runner}" "{script_path}" --minimized'

def is_autostart_enabled() -> bool:
    """Проверяет, включен ли автозапуск в реестре."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return bool(val)
    except Exception:
        return False

def set_autostart(enabled: bool) -> bool:
    """Включает или выключает автозапуск приложения вместе с Windows."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            cmd = get_launch_command()
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        return False
