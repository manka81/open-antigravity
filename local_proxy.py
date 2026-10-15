"""
Local GeoHide Smart Proxy Module
Обеспечивает выборочную маршрутизацию трафика (Per-Process Proxy) только для
процессов Antigravity.exe, language_server.exe и CLI agy.exe.
Исключает авторизационные домены (Google OAuth2 / Accounts), чтобы вход в аккаунт
всегда происходил напрямую без ошибок EOF.
"""

import socket
import select
import threading
import time
import os
import sys
import json
import re
from typing import Callable, Optional, Set

# Список проверенных рабочих IP GeoHide SNI-прокси
WORKING_GEOHIDE_IPS = [
    "193.233.112.68",
    "193.233.112.88",
    "193.233.112.67",
    "45.155.204.190",
    "37.230.192.51"
]

# Авторизационные и системные домены, которые ВСЕГДА идут напрямую
EXCLUDED_AUTH_DOMAINS = {
    "oauth2.googleapis.com",
    "accounts.google.com",
    "accounts.youtube.com",
    "myaccount.google.com",
    "login.google.com",
    "oauth.google.com",
    "identitytoolkit.googleapis.com",
    "securetoken.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "www.googleapis.com",
    "www.google.com",
    "google.com",
    "github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "ssl.gstatic.com",
    "www.gstatic.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "play.google.com"
}


# Встроенные базовые AI-домены, требующие GeoHide
DEFAULT_AI_DOMAINS = {
    "gemini.google.com",
    "gemini.google",
    "generativelanguage.googleapis.com",
    "aistudio.google.com",
    "aicode.googleapis.com",
    "antigravity.google",
    "www.antigravity.google",
    "daily-cloudcode-pa.googleapis.com",
    "aisandbox-pa.googleapis.com",
    "bard.google.com",
    "notebooklm.google.com",
    "notebooklm.google",
    "alkalicore-pa.clients6.google.com",
    "alkalimakersuite-pa.clients6.google.com",
    "geminiweb-pa.clients6.google.com",
    "deepmind.google",
    "openai.com",
    "api.openai.com",
    "chat.openai.com",
    "chatgpt.com",
    "anthropic.com",
    "api.anthropic.com",
    "claude.ai"
}

def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.abspath(__file__))

def load_geohide_database() -> Set[str]:
    """Загружает базу доменов GeoHide из json или системного файла hosts."""
    domains = set(DEFAULT_AI_DOMAINS)
    
    # 1. Попытка загрузить из geohide_domains.json
    json_path = os.path.join(get_base_dir(), "geohide_domains.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for d in data:
                    domains.add(d.lower().strip())
        except Exception:
            pass

    # 2. Попытка прочитать из системного hosts, если там уже есть записи GeoHide
    windir = os.environ.get("WINDIR", r"C:\Windows")
    hosts_path = os.path.join(windir, "System32", "drivers", "etc", "hosts")
    if os.path.exists(hosts_path):
        try:
            with open(hosts_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2 and not parts[0].startswith("#"):
                        # Проверяем, является ли IP адресом GeoHide
                        ip = parts[0]
                        if any(ip.startswith(prefix) for prefix in ["193.233.", "159.194.", "37.230.", "45.155.", "46.8."]):
                            domains.add(parts[1].lower().strip())
        except Exception:
            pass

    # Гарантируем отсутствие авторизационных доменов в базе проксирования
    domains.difference_update(EXCLUDED_AUTH_DOMAINS)
    return domains


class GeoHideSmartProxy:
    def __init__(self, host: str = "127.0.0.1", port: int = 8899, log_callback: Optional[Callable[[str], None]] = None):
        self.host = host
        self.port = port
        self.log_callback = log_callback
        self.server_socket: Optional[socket.socket] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._active_connections = 0

        # Загружаем актуальную базу доменов GeoHide
        self.geohide_domains = load_geohide_database()

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)

    def is_geohide_target(self, host: str) -> bool:
        """
        Проверяет, должен ли запрос идти через GeoHide:
        - Возвращает False для Google OAuth2, Accounts и других не-AI сервисов.
        - Возвращает True только для сервисов Gemini, OpenAI, Claude и базы GeoHide.
        """
        host = host.lower().strip()

        # 1. Авторизационные домены ВСЕГДА напрямую (иначе ошибка oauth2 token EOF)
        if host in EXCLUDED_AUTH_DOMAINS:
            return False
        if host.startswith("accounts.") or host.startswith("oauth.") or host.startswith("login."):
            return False

        # 2. Точное совпадение в базе GeoHide
        if host in self.geohide_domains:
            return True

        # 3. AI паттерны (Gemini, Claude, OpenAI)
        if "gemini" in host or "aistudio" in host or "generativelanguage" in host:
            return True
        if host.endswith(".openai.com") or host.endswith(".anthropic.com") or host.endswith(".claude.ai"):
            return True

        return False

    def start(self) -> bool:
        if self.is_running:
            return True

        # Обновляем базу доменов при запуске
        self.geohide_domains = load_geohide_database()

        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(64)
            self.server_socket.settimeout(1.0)
            self.is_running = True

            self._thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._thread.start()
            self.log(f"Локальный Smart Proxy запущен на http://{self.host}:{self.port} (активно {len(self.geohide_domains)} правил)")
            return True
        except Exception as e:
            self.log(f"Не удалось запустить Smart Proxy на {self.host}:{self.port}: {e}")
            self.is_running = False
            return False

    def stop(self):
        if not self.is_running:
            return

        self.is_running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.log("Локальный Smart Proxy остановлен.")

    def _accept_loop(self):
        while self.is_running:
            try:
                client_sock, client_addr = self.server_socket.accept()
                threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _handle_client(self, client_sock: socket.socket):
        self._active_connections += 1
        try:
            client_sock.settimeout(10.0)
            req_data = b""
            while b"\r\n\r\n" not in req_data:
                chunk = client_sock.recv(4096)
                if not chunk:
                    client_sock.close()
                    return
                req_data += chunk
                if len(req_data) > 65536:
                    client_sock.close()
                    return

            header_text = req_data.split(b"\r\n\r\n")[0].decode("utf-8", errors="ignore")
            lines = header_text.splitlines()
            if not lines:
                client_sock.close()
                return

            first_line = lines[0].strip()
            parts = first_line.split(" ")
            if len(parts) < 2:
                client_sock.close()
                return

            method = parts[0].upper()
            target = parts[1]

            if method == "CONNECT":
                self._handle_connect(client_sock, target)
            else:
                self._handle_plain_http(client_sock, method, target, req_data)

        except Exception:
            pass
        finally:
            self._active_connections = max(0, self._active_connections - 1)
            try:
                client_sock.close()
            except Exception:
                pass

    def _handle_connect(self, client_sock: socket.socket, target: str):
        if ":" in target:
            host, port_str = target.split(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 443
        else:
            host = target
            port = 443

        use_geohide = self.is_geohide_target(host)
        remote_sock = None

        if use_geohide:
            # Подключаемся к рабочим IP GeoHide
            for gh_ip in WORKING_GEOHIDE_IPS:
                try:
                    remote_sock = socket.create_connection((gh_ip, port), timeout=4.0)
                    self.log(f"CONNECT {host}:{port} -> GeoHide [{gh_ip}]")
                    break
                except Exception:
                    continue

        if not remote_sock:
            # Прямое подключение (для OAuth, аккаунтов, обычных сайтов или при сбое GeoHide)
            try:
                remote_sock = socket.create_connection((host, port), timeout=6.0)
                if use_geohide:
                    self.log(f"CONNECT {host}:{port} -> Прямое (GeoHide недоступен)")
                else:
                    self.log(f"CONNECT {host}:{port} -> Прямое (OAuth/Стандарт)")
            except Exception as e:
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                return

        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        self._pipe_bidirectional(client_sock, remote_sock)

    def _handle_plain_http(self, client_sock: socket.socket, method: str, url: str, initial_data: bytes):
        host = ""
        port = 80
        if url.startswith("http://"):
            url_no_scheme = url[7:]
            host_part = url_no_scheme.split("/")[0]
            if ":" in host_part:
                host, p_str = host_part.split(":", 1)
                port = int(p_str)
            else:
                host = host_part

        if not host:
            client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return

        try:
            remote_sock = socket.create_connection((host, port), timeout=6.0)
            remote_sock.sendall(initial_data)
            self._pipe_bidirectional(client_sock, remote_sock)
        except Exception:
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")

    def _pipe_bidirectional(self, sock1: socket.socket, sock2: socket.socket):
        sockets = [sock1, sock2]
        sock1.setblocking(False)
        sock2.setblocking(False)

        while self.is_running:
            try:
                rlist, _, xlist = select.select(sockets, [], sockets, 30.0)
                if xlist or not rlist:
                    break

                for s in rlist:
                    other = sock2 if s is sock1 else sock1
                    data = s.recv(16384)
                    if not data:
                        return
                    other.sendall(data)
            except Exception:
                break
