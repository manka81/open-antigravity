"""
GeoHide Core Module
Управление DNS, файлом hosts и диагностикой состояния подключения GeoHide.
"""

import os
import re
import sys
import subprocess
import urllib.request
import urllib.error
import time

# Список известных IP-адресов GeoHide DNS
GEOHIDE_DNS_IPS = {
    "159.194.200.33",
    "37.230.192.51",
    "193.233.112.67",
    "193.233.112.88",
    "45.155.204.190",
    "46.8.158.6",
    "193.233.112.68",
    "5.175.161.3",
    "5.175.161.40",
    "45.13.237.213",
    "31.25.239.132",
    "143.20.64.192",
    "192.255.159.240",
    "192.255.159.241",
    "192.3.233.253",
    "107.175.76.134"
}

PRIMARY_DNS = ("159.194.200.33", "37.230.192.51")
GEOHIDE_HOSTS_URL = "https://raw.githubusercontent.com/Internet-Helper/GeoHideDNS/main/hosts/hosts"
TAG_START = "# === GEOHIDE DNS START ==="
TAG_END = "# === GEOHIDE DNS END ==="

DEFAULT_HOSTS_TEMPLATE = """# Copyright (c) 1993-2009 Microsoft Corp.
#
# This is a sample HOSTS file used by Microsoft TCP/IP for Windows.
#
# localhost name resolution is handled within DNS itself.
127.0.0.1       localhost
::1             localhost
"""

def get_hosts_path() -> str:
    """Возвращает абсолютный путь к системному файлу hosts."""
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return os.path.join(windir, "System32", "drivers", "etc", "hosts")

def run_powershell(command: str) -> tuple[int, str, str]:
    """Выполняет команду PowerShell без всплывающих окон."""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def flush_dns() -> bool:
    """Очищает локальный DNS кэш."""
    try:
        res = subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        return res.returncode == 0
    except Exception:
        return False

def ping_host(host: str = "gemini.google.com") -> tuple[bool, str]:
    """Проверяет пинг до целевого хоста."""
    try:
        res = subprocess.run(
            ["ping", host, "-n", "1", "-w", "2000"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        output = res.stdout
        if "TTL=" in output or "ttl=" in output:
            match = re.search(r"[=<](\d+)\s*ms", output, re.IGNORECASE)
            time_str = f"{match.group(1)} ms" if match else "OK"
            return True, time_str
        else:
            return False, "Таймаут / Недоступен"
    except Exception as e:
        return False, str(e)

def get_active_adapters_dns() -> list[dict]:
    """
    Получает информацию о DNS серверах на всех активных адаптерах.
    Возвращает список словарей: [{'alias': ..., 'dns': [...], 'is_geohide': bool}]
    """
    ps_cmd = (
        "Get-NetAdapter | Where-Object Status -eq 'Up' | "
        "Get-DnsClientServerAddress -AddressFamily IPv4 | "
        "ForEach-Object { "
        "  $alias = $_.InterfaceAlias; "
        "  $dns = $_.ServerAddresses -join ','; "
        "  Write-Output \"$alias|$dns\" "
        "}"
    )
    code, out, _ = run_powershell(ps_cmd)
    adapters = []
    if code != 0 or not out:
        return adapters

    for line in out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 1)
        alias = parts[0].strip()
        dns_str = parts[1].strip()
        dns_list = [d.strip() for d in dns_str.split(",") if d.strip()]
        
        has_geohide = any(dns_ip in GEOHIDE_DNS_IPS for dns_ip in dns_list)
        adapters.append({
            "alias": alias,
            "dns": dns_list,
            "is_geohide": has_geohide
        })
    return adapters

def check_hosts_status() -> dict:
    """
    Проверяет файл hosts на наличие записей GeoHide.
    Возвращает словарь со статусом и метаданными.
    """
    path = get_hosts_path()
    if not os.path.exists(path):
        return {"exists": False, "has_geohide": False, "count": 0, "date": None}

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        has_marker = (
            TAG_START in content or
            "geohide.ru" in content or
            "GeoHide DNS" in content or
            "gemini.google.com" in content
        )

        date_match = re.search(r"### geohide\.ru: hosts file\s*#\s*[^:\n]+:\s*([0-9\.\:\s]+)", content)
        version_date = date_match.group(1).strip() if date_match else None

        # Считаем количество записей
        lines = content.splitlines()
        geohide_lines_count = sum(
            1 for line in lines 
            if line.strip() and not line.strip().startswith("#") and any(ip in line for ip in GEOHIDE_DNS_IPS)
        )

        return {
            "exists": True,
            "has_geohide": has_marker,
            "count": geohide_lines_count,
            "date": version_date
        }
    except Exception as e:
        return {"exists": True, "has_geohide": False, "error": str(e), "count": 0, "date": None}

def get_current_status() -> dict:
    """
    Комплексная проверка текущего состояния GeoHide.
    Возвращает статус: 'active', 'inactive', 'partial'
    """
    adapters = get_active_adapters_dns()
    hosts_info = check_hosts_status()
    
    # Считаем активные адаптеры с GeoHide
    geohide_adapters = [a for a in adapters if a["is_geohide"]]
    dns_active = len(geohide_adapters) > 0
    hosts_active = hosts_info["has_geohide"]

    if dns_active and hosts_active:
        state = "active"
        summary = "GeoHide активен (DNS и hosts настроены)"
    elif not dns_active and not hosts_active:
        state = "inactive"
        summary = "GeoHide отключен (Стандартный DNS)"
    else:
        state = "partial"
        if dns_active and not hosts_active:
            summary = "Частично: DNS активен, но hosts не настроен"
        else:
            summary = "Частично: hosts настроен, но DNS стандартный"

    return {
        "state": state,
        "summary": summary,
        "adapters": adapters,
        "hosts": hosts_info,
        "geohide_adapters_count": len(geohide_adapters),
        "total_adapters_count": len(adapters)
    }

def enable_geohide(log_callback=None) -> tuple[bool, str]:
    """
    Включает GeoHide:
    1. Устанавливает DNS на всех активных адаптерах.
    2. Скачивает свежий hosts файл.
    3. Добавляет/обновляет секцию GeoHide в системном файле hosts.
    4. Очищает кэш DNS.
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    log("Начало активации GeoHide...")
    
    # 1. Скачивание hosts с GitHub
    log("Загрузка свежего списка hosts с GitHub...")
    try:
        req = urllib.request.Request(
            GEOHIDE_HOSTS_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            geohide_hosts_content = response.read().decode("utf-8", errors="ignore")
        log(f"Список hosts успешно загружен ({len(geohide_hosts_content.splitlines())} строк)")
    except Exception as e:
        log(f"Ошибка загрузки hosts: {e}")
        return False, f"Не удалось загрузить hosts с GitHub: {e}"

    # 2. Установка DNS
    log(f"Установка DNS серверов: {PRIMARY_DNS[0]}, {PRIMARY_DNS[1]}...")
    dns_cmd = (
        f"Get-NetAdapter | Where-Object Status -eq 'Up' | "
        f"Set-DnsClientServerAddress -ServerAddresses ('{PRIMARY_DNS[0]}', '{PRIMARY_DNS[1]}')"
    )
    code, _, err = run_powershell(dns_cmd)
    if code != 0:
        log(f"Ошибка настройки DNS: {err}")
        return False, f"Ошибка настройки DNS: {err}"
    log("DNS серверы успешно назначены на всех активных адаптерах.")

    # 3. Обновление файла hosts
    hosts_path = get_hosts_path()
    log(f"Обновление файла hosts: {hosts_path}...")
    try:
        existing_content = ""
        if os.path.exists(hosts_path):
            with open(hosts_path, "r", encoding="utf-8", errors="ignore") as f:
                existing_content = f.read()

        # Очищаем старые записи GeoHide, если они были
        clean_content = _remove_geohide_from_text(existing_content).strip()
        if not clean_content:
            clean_content = DEFAULT_HOSTS_TEMPLATE.strip()

        # Добавляем новый блок с четкими тегами
        new_block = f"\n\n{TAG_START}\n{geohide_hosts_content.strip()}\n{TAG_END}\n"
        final_content = clean_content + new_block

        with open(hosts_path, "w", encoding="utf-8") as f:
            f.write(final_content)
        log("Файл hosts успешно обновлен!")
    except PermissionError:
        log("Ошибка: Недостаточно прав для записи в файл hosts. Требуются права Администратора!")
        return False, "Недостаточно прав для записи в hosts (запустите от Администратора)."
    except Exception as e:
        log(f"Ошибка записи в hosts: {e}")
        return False, f"Ошибка записи в hosts: {e}"

    # 4. Очистка DNS кэша
    log("Очистка локального DNS кэша (ipconfig /flushdns)...")
    if flush_dns():
        log("DNS кэш успешно сброшен.")
    else:
        log("Предупреждение: не удалось сбросить DNS кэш.")

    # 5. Проверка соединения
    log("Проверка доступности gemini.google.com...")
    ping_ok, ping_msg = ping_host("gemini.google.com")
    log(f"Статус проверки Gemini: {ping_msg}")

    log("GeoHide успешно активирован!")
    return True, "GeoHide успешно активирован и готов к работе."

def disable_geohide(log_callback=None) -> tuple[bool, str]:
    """
    Отключает GeoHide:
    1. Сбрасывает DNS на автоматический режим (DHCP).
    2. Удаляет записи GeoHide из файла hosts.
    3. Очищает кэш DNS.
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    log("Начало отключения GeoHide...")

    # 1. Сброс DNS
    log("Сброс DNS адаптеров на автоматическое получение (DHCP)...")
    reset_cmd = "Get-NetAdapter | Where-Object Status -eq 'Up' | Set-DnsClientServerAddress -ResetServerAddresses"
    code, _, err = run_powershell(reset_cmd)
    if code != 0:
        log(f"Ошибка сброса DNS: {err}")
        return False, f"Ошибка сброса DNS: {err}"
    log("DNS серверы успешно сброшены в режим DHCP.")

    # 2. Очистка файла hosts
    hosts_path = get_hosts_path()
    log(f"Очистка файла hosts от записей GeoHide...")
    try:
        existing_content = ""
        if os.path.exists(hosts_path):
            with open(hosts_path, "r", encoding="utf-8", errors="ignore") as f:
                existing_content = f.read()

        clean_content = _remove_geohide_from_text(existing_content).strip()
        if not clean_content:
            clean_content = DEFAULT_HOSTS_TEMPLATE.strip()

        with open(hosts_path, "w", encoding="utf-8") as f:
            f.write(clean_content + "\n")
        log("Файл hosts очищен.")
    except PermissionError:
        log("Ошибка: Недостаточно прав для редактирования файла hosts.")
        return False, "Недостаточно прав для записи в hosts (запустите от Администратора)."
    except Exception as e:
        log(f"Ошибка очистки hosts: {e}")
        return False, f"Ошибка очистки hosts: {e}"

    # 3. Очистка DNS кэша
    log("Очистка локального DNS кэша...")
    if flush_dns():
        log("DNS кэш успешно сброшен.")
    else:
        log("Предупреждение: не удалось сбросить DNS кэш.")

    log("GeoHide полностью отключен. Сеть возвращена в исходное состояние.")
    return True, "GeoHide успешно отключен."

def _remove_geohide_from_text(text: str) -> str:
    """Удаляет блок GeoHide из содержимого файла hosts."""
    # 1. Если есть теги TAG_START и TAG_END
    if TAG_START in text and TAG_END in text:
        pattern = re.escape(TAG_START) + r".*?" + re.escape(TAG_END)
        text = re.sub(pattern, "", text, flags=re.DOTALL)

    # 2. Удаление legacy записей (например от прямого powershell Invoke-WebRequest)
    lines = text.splitlines()
    clean_lines = []
    skip_geohide_block = False

    for line in lines:
        stripped = line.strip()
        if "### geohide.ru: hosts file" in stripped:
            skip_geohide_block = True
            continue
        
        # Если блок продолжается или содержит известные IP
        if skip_geohide_block:
            # Если дошли до конца или до пустых строк не-geohide
            # Проверяем, относится ли строка к geohide
            if any(ip in stripped for ip in GEOHIDE_DNS_IPS) or stripped.startswith("#"):
                continue
            else:
                skip_geohide_block = False

        if any(ip in stripped for ip in GEOHIDE_DNS_IPS):
            continue

        clean_lines.append(line)

    return "\n".join(clean_lines).strip()
