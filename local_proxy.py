"""
Local GeoHide Smart Proxy Module
Обеспечивает выборочную маршрутизацию трафика (Per-Process Proxy) только для
процессов Antigravity.exe и language_server.exe без изменения общесистемных
настроек DNS и файла hosts.
"""

import socket
import select
import threading
import time
import re
from typing import Callable, Optional

# Список проверенных рабочих IP GeoHide SNI-прокси
WORKING_GEOHIDE_IPS = [
    "193.233.112.68",
    "193.233.112.88",
    "193.233.112.67",
    "45.155.204.190",
    "37.230.192.51"
]

# Паттерны доменов, требующих маршрутизации через GeoHide (Google AI, Gemini, OpenAI и др.)
GEOHIDE_DOMAINS_PATTERNS = [
    r"gemini\.google\.com",
    r".*\.gemini\.google\.com",
    r"generativelanguage\.googleapis\.com",
    r".*\.googleapis\.com",
    r"aistudio\.google\.com",
    r"alkalimakersuite-pa\.clients6\.google\.com",
    r"openai\.com",
    r".*\.openai\.com",
    r".*\.anthropic\.com",
    r"claude\.ai",
    r".*\.claude\.ai"
]

class GeoHideSmartProxy:
    def __init__(self, host: str = "127.0.0.1", port: int = 8899, log_callback: Optional[Callable[[str], None]] = None):
        self.host = host
        self.port = port
        self.log_callback = log_callback
        self.server_socket: Optional[socket.socket] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._active_connections = 0

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)

    def is_geohide_target(self, host: str) -> bool:
        host = host.lower().strip()
        for pattern in GEOHIDE_DOMAINS_PATTERNS:
            if re.fullmatch(pattern, host):
                return True
        return False

    def start(self) -> bool:
        if self.is_running:
            return True

        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(64)
            self.server_socket.settimeout(1.0)
            self.is_running = True

            self._thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._thread.start()
            self.log(f"Локальный Smart Proxy запущен на http://{self.host}:{self.port}")
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

        except Exception as e:
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
            # Стандартное прямое разрешение
            try:
                remote_sock = socket.create_connection((host, port), timeout=6.0)
                if use_geohide:
                    self.log(f"CONNECT {host}:{port} -> Прямое (GeoHide недоступен)")
            except Exception as e:
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                return

        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        self._pipe_bidirectional(client_sock, remote_sock)

    def _handle_plain_http(self, client_sock: socket.socket, method: str, url: str, initial_data: bytes):
        # Парсинг URL
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
