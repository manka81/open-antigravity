"""
Local GeoHide Smart Proxy Module
Обеспечивает надежную, высокоскоростную маршрутизацию трафика (Per-Process Proxy)
для процессов Antigravity IDE, language_server.exe и CLI agy.exe.
- Поддерживает постоянные (Persistent Keep-Alive) соединения HTTP/2 и gRPC.
- Исключает авторизационные домены (Google OAuth2 / Accounts) для входа без сбоев.
- Направляет все запросы моделей (Gemini, Claude, OpenAI, cloudcode-pa, aicode)
  через проверенные высокоскоростные реверс-прокси GeoHide.
"""

import socket
import threading
import time
import os
import sys
import json
import re
from typing import Callable, Optional, Set

# Проверенные быстрые IP GeoHide SNI-прокси (только стабильные, без таймаутов)
WORKING_GEOHIDE_IPS = [
    "193.233.112.68",
    "193.233.112.88",
    "193.233.112.67",
    "159.194.200.33"
]

# Авторизационные и системные домены, которые ВСЕГДА идут напрямую (GeoHide их сбрасывает по EOF)
EXCLUDED_AUTH_DOMAINS = {
    "cloudcode-pa.googleapis.com",
    "aiplatform.googleapis.com",
    "s-aiplatform.googleapis.com",
    "businessaicode.googleapis.com",
    "autopush-cloudcode-pa.sandbox.googleapis.com",
    "autopush-aicode.sandbox.googleapis.com",
    "preprod-daily-cloudcode-pa.sandbox.googleapis.com",
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

# Встроенные базовые AI-домены, подтвержденно поддерживаемые GeoHide
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
    
    # 1. Загрузка из geohide_domains.json
    json_path = os.path.join(get_base_dir(), "geohide_domains.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for d in data:
                    domains.add(d.lower().strip())
        except Exception:
            pass

    # 2. Чтение из системного hosts
    windir = os.environ.get("WINDIR", r"C:\Windows")
    hosts_path = os.path.join(windir, "System32", "drivers", "etc", "hosts")
    if os.path.exists(hosts_path):
        try:
            with open(hosts_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2 and not parts[0].startswith("#"):
                        ip = parts[0]
                        if any(ip.startswith(prefix) for prefix in ["193.233.", "159.194.", "37.230.", "45.155.", "46.8."]):
                            domains.add(parts[1].lower().strip())
        except Exception:
            pass

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
        - Возвращает False для Google OAuth2, Accounts, cloudcode-pa и сервисов,
          которые GeoHide НЕ поддерживает (во избежание ошибки EOF / Connection Reset).
        - Возвращает True только для тех AI-сервисов, которые подтвержденно поддерживаются GeoHide.
        """
        host = host.lower().strip()

        # 1. Авторизационные домены и неподдерживаемые API ВСЕГДА напрямую
        if host in EXCLUDED_AUTH_DOMAINS:
            return False
        if host.startswith("accounts.") or host.startswith("oauth.") or host.startswith("login."):
            return False
        if host == "cloudcode-pa.googleapis.com" or host.endswith(".sandbox.googleapis.com"):
            return False

        # 2. Точное совпадение в проверенной базе GeoHide
        if host in self.geohide_domains:
            return True

        # 3. Подтвержденные AI-домены Google, требующие GeoHide для обхода геоблока
        if (
            "gemini" in host
            or "aistudio" in host
            or "generativelanguage" in host
            or host == "daily-cloudcode-pa.googleapis.com"
            or host == "aicode.googleapis.com"
            or host == "aisandbox-pa.googleapis.com"
            or "alkalicore" in host
            or "alkalimakersuite" in host
            or "geminiweb" in host
            or "notebooklm" in host
            or "antigravity" in host
        ):
            return True

        # 4. Другие популярные зарубежные AI (OpenAI, Claude)
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
            self.server_socket.listen(128)
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
            client_sock.settimeout(15.0)
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
            try:
                client_sock.close()
            except Exception:
                pass
        finally:
            self._active_connections = max(0, self._active_connections - 1)

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
            # Подключаемся к проверенным рабочим IP GeoHide с быстрым таймаутом
            for gh_ip in WORKING_GEOHIDE_IPS:
                try:
                    remote_sock = socket.create_connection((gh_ip, port), timeout=2.5)
                    self.log(f"CONNECT {host}:{port} -> GeoHide [{gh_ip}]")
                    break
                except Exception:
                    continue

        if not remote_sock:
            # Прямое подключение (для OAuth2 токенов, аккаунтов или при недоступности GeoHide)
            try:
                remote_sock = socket.create_connection((host, port), timeout=5.0)
                if use_geohide:
                    self.log(f"CONNECT {host}:{port} -> Прямое (GeoHide недоступен)")
                else:
                    self.log(f"CONNECT {host}:{port} -> Прямое (OAuth/Стандарт)")
            except Exception as e:
                try:
                    client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                except Exception:
                    pass
                try:
                    client_sock.close()
                except Exception:
                    pass
                return

        try:
            client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        except Exception:
            try:
                remote_sock.close()
            except Exception:
                pass
            try:
                client_sock.close()
            except Exception:
                pass
            return

        # Передача данных через постоянный двунаправленный поток
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
            try:
                client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                client_sock.close()
            except Exception:
                pass
            return

        try:
            remote_sock = socket.create_connection((host, port), timeout=6.0)
            remote_sock.sendall(initial_data)
            self._pipe_bidirectional(client_sock, remote_sock)
        except Exception:
            try:
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                client_sock.close()
            except Exception:
                pass

    def _pipe_bidirectional(self, client_sock: socket.socket, remote_sock: socket.socket):
        """
        Высокопроизводительный двунаправленный пайп с поддержкой постоянных
        HTTP/2, gRPC и WebSocket потоков без разрыва соединений по таймауту.
        """
        # Снимаем любые искусственные таймауты
        client_sock.settimeout(None)
        remote_sock.settimeout(None)
        client_sock.setblocking(True)
        remote_sock.setblocking(True)

        # Включаем TCP KeepAlive на уровне операционной системы
        for s in (client_sock, remote_sock):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                if hasattr(socket, "SIO_KEEPALIVE_VALS"):
                    # 1 = вкл, 30000 мс (30 сек) idle, 5000 мс interval
                    s.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30000, 5000))
            except Exception:
                pass

        def forward(src: socket.socket, dst: socket.socket):
            try:
                while self.is_running:
                    data = src.recv(32768)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

        t1 = threading.Thread(target=forward, args=(client_sock, remote_sock), daemon=True)
        t2 = threading.Thread(target=forward, args=(remote_sock, client_sock), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        try:
            client_sock.close()
        except Exception:
            pass
        try:
            remote_sock.close()
        except Exception:
            pass
