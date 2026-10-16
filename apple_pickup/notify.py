"""Fan a message out to phone push (ntfy), Discord, desktop and a beep."""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import webbrowser

import requests

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg):
        self.cfg = cfg

    def send(self, title: str, message: str, url: str = "", urgent: bool = True):
        log.info("NOTIFY: %s - %s", title, message)
        n = self.cfg
        if n.ntfy_topic:
            self._try(self._ntfy, title, message, url, urgent)
        if n.discord_webhook:
            self._try(self._discord, title, message, url)
        if n.desktop:
            self._try(self._desktop, title, message)
        if n.sound and urgent:
            self._try(self._beep)

    def open(self, url: str):
        if self.cfg.open_browser and url:
            webbrowser.open(url)

    def _try(self, fn, *args):
        try:
            fn(*args)
        except Exception as e:  # a broken channel must never stop the watcher
            log.warning("notification via %s failed: %s", fn.__name__, e)

    def _ntfy(self, title, message, url, urgent):
        headers = {
            "Title": title.encode("utf-8"),
            "Priority": "urgent" if urgent else "default",
            "Tags": "iphone,rotating_light" if urgent else "iphone",
        }
        if url:
            headers["Click"] = url
        requests.post(
            f"{self.cfg.ntfy_server.rstrip('/')}/{self.cfg.ntfy_topic}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10,
        ).raise_for_status()

    def _discord(self, title, message, url):
        content = f"**{title}**\n{message}" + (f"\n{url}" if url else "")
        requests.post(self.cfg.discord_webhook, json={"content": content}, timeout=10).raise_for_status()

    def _desktop(self, title, message):
        system = platform.system()
        if system == "Darwin":
            script = f'display notification {_q(message)} with title {_q(title)} sound name "Glass"'
            subprocess.run(["osascript", "-e", script], check=False, timeout=10)
        elif system == "Windows":
            # A MessageBox on a background thread is the dependency-free option.
            import ctypes
            import threading

            threading.Thread(
                target=ctypes.windll.user32.MessageBoxW,
                args=(0, message, title, 0x00041040),  # topmost + info icon
                daemon=True,
            ).start()
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", "-u", "critical", title, message], check=False, timeout=10)

    def _beep(self):
        system = platform.system()
        if system == "Windows":
            import winsound

            for _ in range(5):
                winsound.Beep(1500, 300)
        elif system == "Darwin":
            subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
        else:
            print("\a", end="", flush=True)


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
