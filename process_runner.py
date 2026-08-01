import os
import threading
import subprocess
import queue
import sys

BASE = os.path.dirname(__file__)
PYTHON = sys.executable


class ProcessRunner:
    """Manages a long-lived Python subprocess with stdout pump.

    Thread-safe: uses a generation counter so stale pump threads from
    previous start() calls can't overwrite status from the current process.
    """

    def __init__(self, script_name, status_var, last_line_var, check_var):
        self.script_path = os.path.join(BASE, script_name)
        self.status_var = status_var
        self.last_line_var = last_line_var
        self.check_var = check_var
        self.proc = None
        self.q = queue.Queue()
        self._gen = 0
        self._lock = threading.Lock()

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, extra_args):
        with self._lock:
            if self.is_running():
                return
            self._gen += 1
            gen = self._gen
            self.proc = subprocess.Popen(
                [PYTHON, "-u", self.script_path, *extra_args],
                cwd=BASE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        self.status_var.set("Running")
        self.check_var.set(True)
        threading.Thread(target=self._pump, args=(gen,), daemon=True).start()

    def _pump(self, gen):
        try:
            for line in self.proc.stdout:
                self.q.put(("line", line.rstrip("\n")))
        except ValueError:
            pass
        finally:
            self.q.put(("done", gen))

    def poll_log(self):
        while True:
            try:
                tag, payload = self.q.get_nowait()
                if tag == "done":
                    with self._lock:
                        if payload == self._gen:
                            self.status_var.set("Stopped")
                            self.check_var.set(False)
                            self.proc = None
                elif tag == "line":
                    self.last_line_var.set(payload[:80])
            except queue.Empty:
                break

    def stop(self):
        with self._lock:
            if self.is_running():
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
                self.proc = None
        self.status_var.set("Stopped")
        self.check_var.set(False)
