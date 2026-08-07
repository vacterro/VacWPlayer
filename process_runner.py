import os
import threading
import subprocess
import queue
import sys

BASE = os.path.dirname(__file__)
PYTHON = sys.executable


class ProcessRunner:
    """Manages a long-lived Python subprocess with stdout pump.

    Thread-safe: a generation counter isolates pump threads from previous
    start() calls, so a stale pump can never consume the NEW process's stream
    or overwrite current UI state. The Popen object is captured locally and
    stored on the instance only after a successful spawn; every line/done
    event carries its generation, and poll_log drops stale ones.
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
        """Spawn the child. Returns True on success, False on spawn failure.

        On failure self.proc stays None (never a half-open Popen), the status
        shows a diagnostic and the checkbox stays off - the GUI can never
        look Running without a live child.
        """
        with self._lock:
            if self.is_running():
                return True
            self._gen += 1
            gen = self._gen
            try:
                proc = subprocess.Popen(
                    [PYTHON, "-u", self.script_path, *extra_args],
                    cwd=BASE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.SubprocessError) as e:
                self.status_var.set("Error: %s" % e)
                self.check_var.set(False)
                return False
            self.proc = proc
        self.status_var.set("Running")
        self.check_var.set(True)
        threading.Thread(target=self._pump, args=(proc, gen), daemon=True).start()
        return True

    def _pump(self, proc, gen):
        # `proc` is the captured child from THIS generation - never reads
        # self.proc, so a restarted process's stream cannot be drained by a
        # leftover pump from an older start().
        try:
            for line in proc.stdout:
                self.q.put(("line", gen, line.rstrip("\n")))
        except ValueError:
            pass
        except Exception as e:
            print(f"process_runner: pump error: {e}", file=sys.stderr)
        finally:
            self.q.put(("done", gen))

    def poll_log(self):
        while True:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                break
            tag = item[0]
            if tag == "done":
                gen, payload = item[1], None
            elif tag == "line":
                gen, payload = item[1], item[2]
            else:
                continue
            if gen != self._gen:
                # stale-generation event from an older pump: ignore entirely,
                # lines AND done markers alike.
                continue
            if tag == "done":
                with self._lock:
                    self.status_var.set("Stopped")
                    self.check_var.set(False)
                    self.proc = None
            else:
                self.last_line_var.set(payload[:80])

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
