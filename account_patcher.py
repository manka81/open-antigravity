"""
Account Patcher Module
Разблокировка входа в Antigravity с любого аккаунта Google (снятие региональных
и аккаунтных ограничений 'ineligible' / 400).
Побайтово заменяет дескриптор protobuf: 'ineligible' -> 'inexigible' в бинарниках
language_server.exe и agy.exe без изменения длины файла и смещений.
Безопасная работа: никаких принудительных закрытий без явного согласия пользователя.
"""

import os
import sys
import shutil
import subprocess
import time
from typing import List, Dict, Tuple

ORIGINAL_SIGNATURE = b"ineligible"
PATCHED_SIGNATURE = b"inexigible"

def find_target_binaries() -> List[str]:
    """
    Динамически находит все целевые бинарники Language Server и CLI (agy),
    подлежащие разблокировке на этой машине.
    """
    targets = []
    
    # 1. Известные пути в %LOCALAPPDATA%
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        candidates = [
            os.path.join(local_app_data, "Programs", "antigravity", "resources", "bin", "language_server.exe"),
            os.path.join(local_app_data, "agy", "bin", "agy.exe"),
            os.path.join(local_app_data, "Programs", "antigravity", "resources", "app", "extensions", "antigravity", "bin", "language_server_windows_x64.exe"),
            os.path.join(local_app_data, "Programs", "antigravity", "resources", "app", "extensions", "antigravity", "bin", "language_server.exe")
        ]
        for c in candidates:
            if os.path.exists(c) and c not in targets:
                targets.append(c)

    # 2. Поиск в PATH
    agy_which = shutil.which("agy.exe") or shutil.which("agy")
    if agy_which and os.path.exists(agy_which) and agy_which not in targets:
        targets.append(os.path.abspath(agy_which))

    # 3. Сканирование папок Antigravity
    for base in [os.environ.get("LOCALAPPDATA", ""), os.environ.get("PROGRAMFILES", "")]:
        if not base or not os.path.exists(base):
            continue
        try:
            for root, _, files in os.walk(base):
                if "antigravity" in root.lower() or "agy" in root.lower():
                    for f in files:
                        f_lower = f.lower()
                        if (f_lower.startswith("language_server") and f_lower.endswith(".exe")) or f_lower == "agy.exe":
                            full = os.path.join(root, f)
                            if full not in targets and os.path.exists(full):
                                targets.append(full)
        except Exception:
            pass

    return targets

def get_binary_status(path: str) -> Dict[str, any]:
    """Проверяет статус патча для конкретного исполняемого файла."""
    if not os.path.exists(path):
        return {"exists": False, "status": "missing", "orig": 0, "patched": 0}

    try:
        with open(path, "rb") as f:
            data = f.read()

        orig_cnt = data.count(ORIGINAL_SIGNATURE)
        patch_cnt = data.count(PATCHED_SIGNATURE)

        if patch_cnt > 0 and orig_cnt == 0:
            status = "patched"
        elif orig_cnt > 0:
            status = "unpatched"
        else:
            status = "unknown"

        return {
            "exists": True,
            "status": status,
            "orig": orig_cnt,
            "patched": patch_cnt,
            "size": len(data),
            "name": os.path.basename(path)
        }
    except Exception as e:
        return {"exists": True, "status": "error", "error": str(e), "orig": 0, "patched": 0}

def get_overall_patch_status() -> Dict[str, any]:
    """Возвращает общий статус разблокировки аккаунтов для всех найденных бинарников."""
    targets = find_target_binaries()
    if not targets:
        return {"status": "none_found", "total": 0, "patched": 0, "targets": []}

    details = []
    patched_count = 0
    for t in targets:
        info = get_binary_status(t)
        info["path"] = t
        details.append(info)
        if info["status"] == "patched":
            patched_count += 1

    if patched_count == len(targets) and len(targets) > 0:
        overall = "fully_patched"
    elif patched_count > 0:
        overall = "partially_patched"
    else:
        overall = "unpatched"

    return {
        "status": overall,
        "total": len(targets),
        "patched": patched_count,
        "targets": details
    }

def kill_locking_processes():
    """Завершает процессы language_server и agy для освобождения файлов."""
    procs = ["language_server.exe", "language_server_windows_x64.exe", "agy.exe"]
    for p in procs:
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", p],
                capture_output=True,
                text=True,
                creationflags=0x08000000
            )
        except Exception:
            pass
    time.sleep(1.0)

def patch_binary(path: str, force_kill: bool = False) -> Tuple[bool, str]:
    """Применяет патч разблокировки к одному файлу."""
    if not os.path.exists(path):
        return False, f"Файл не найден: {path}"

    try:
        with open(path, "rb") as f:
            data = f.read()

        orig_cnt = data.count(ORIGINAL_SIGNATURE)
        if orig_cnt == 0:
            if data.count(PATCHED_SIGNATURE) > 0:
                return True, "Уже разблокирован"
            return False, "Сигнатура ineligible не найдена"

        # Создаем резервную копию, если её еще нет
        bak_path = path + ".ag_bak"
        if not os.path.exists(bak_path):
            try:
                shutil.copyfile(path, bak_path)
            except Exception:
                pass

        # Побайтовая замена (ineligible -> inexigible)
        patched_data = data.replace(ORIGINAL_SIGNATURE, PATCHED_SIGNATURE)

        # Атомарная запись через временный файл
        tmp_path = path + f".{os.getpid()}.agtmp"
        with open(tmp_path, "wb") as f:
            f.write(patched_data)

        try:
            os.replace(tmp_path, path)
        except PermissionError:
            if force_kill:
                kill_locking_processes()
                os.replace(tmp_path, path)
            else:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                return False, "Файл заблокирован запущенным процессом. Закройте Antigravity."

        return True, f"Разблокирован ({orig_cnt} правил)"
    except Exception as e:
        return False, str(e)

def unpatch_binary(path: str, force_kill: bool = False) -> Tuple[bool, str]:
    """Откатывает патч к исходному состоянию."""
    if not os.path.exists(path):
        return False, f"Файл не найден: {path}"

    try:
        bak_path = path + ".ag_bak"
        if os.path.exists(bak_path):
            try:
                if force_kill:
                    kill_locking_processes()
                shutil.copyfile(bak_path, path)
                os.remove(bak_path)
                return True, "Восстановлен из бэкапа"
            except PermissionError:
                if force_kill:
                    kill_locking_processes()
                    shutil.copyfile(bak_path, path)
                    os.remove(bak_path)
                    return True, "Восстановлен из бэкапа"
                return False, "Файл заблокирован. Закройте Antigravity."
            except Exception:
                pass

        with open(path, "rb") as f:
            data = f.read()

        patched_cnt = data.count(PATCHED_SIGNATURE)
        if patched_cnt == 0:
            return True, "Уже в исходном состоянии"

        unpatched_data = data.replace(PATCHED_SIGNATURE, ORIGINAL_SIGNATURE)
        tmp_path = path + f".{os.getpid()}.agtmp"
        with open(tmp_path, "wb") as f:
            f.write(unpatched_data)

        try:
            os.replace(tmp_path, path)
        except PermissionError:
            if force_kill:
                kill_locking_processes()
                os.replace(tmp_path, path)
            else:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                return False, "Файл заблокирован. Закройте Antigravity."

        return True, f"Восстановлен ({patched_cnt} правил)"
    except Exception as e:
        return False, str(e)

def patch_all(force_kill: bool = False) -> Tuple[bool, str]:
    """Разблокирует все найденные бинарники Antigravity."""
    targets = find_target_binaries()
    if not targets:
        return False, "Бинарники Antigravity не найдены на компьютере."

    success_list = []
    fail_list = []
    for t in targets:
        name = os.path.basename(t)
        ok, msg = patch_binary(t, force_kill=force_kill)
        if ok:
            success_list.append(f"{name}: {msg}")
        else:
            fail_list.append(f"{name}: {msg}")

    if not fail_list:
        return True, f"Все компоненты успешно разблокированы! ({len(success_list)} файлов). Теперь можно входить с любого аккаунта."
    elif success_list:
        return True, f"Частично разблокировано. Успешно: {', '.join(success_list)}. Ошибки: {', '.join(fail_list)}"
    else:
        return False, f"Не удалось разблокировать: {'; '.join(fail_list)}"

def unpatch_all(force_kill: bool = False) -> Tuple[bool, str]:
    """Возвращает все бинарники в исходное состояние."""
    targets = find_target_binaries()
    if not targets:
        return True, "Компоненты Antigravity не найдены."

    results = []
    for t in targets:
        name = os.path.basename(t)
        ok, msg = unpatch_binary(t, force_kill=force_kill)
        results.append(f"{name}: {msg}")

    return True, "; ".join(results)
