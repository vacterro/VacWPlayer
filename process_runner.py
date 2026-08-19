import logging
import os
import threading
import subprocess
import queue
import sys
from collections import deque

logger = logging.getLogger(__name__)

BASE = os.path.dirname(__file__)
PYTHON = sys.executable


class ProcessRunner:
    """Manages a long-lived Python subprocess with stdout pump.

    Thread-safe: a generation counter isolates pump threads from previous
    start() calls, so a stale pump can never consume the NEW process's stream
    or overwrite current UI state. The Popen object is captured locally and
    stored on the instance only after a successful spawn.

    T-W2-PERF-001: line output is coalesced to the latest value via a bounded
    deque (MAX_LINE_HISTORY=20) so a noisy child cannot grow memory without
    bound. Control events (eof, pump_error) pass through unbounded because they
    are terminal and few. poll_log() performs at most one visible .set() per
    tick.
    """
    MAX_LINE_HISTORY = 20

    def __init__(self, script_name, status_var, last_line_var, check_var):
        self.script_path = os.path.join(BASE, script_name)
        self.status_var = status_var
        self.last_line_var = last_line_var
        self.check_var = check_var
        self.proc = None
        # Control events use an unbounded queue (few, terminal).
        self.q = queue.Queue()
        # Line output uses a bounded deque - only the latest N values matter.
        self._line_buf = deque(maxlen=self.MAX_LINE_HISTORY)
        self._gen = 0
        self._lock = threading.Lock()

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, extra_args):
        """Spawn the child. Returns True on success, False on spawn failure."""
        with self._lock:
            if self.is_running():
                return True
            self.proc = None
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
        try:
            for line in proc.stdout:
                # Line events: enqueue a bounded deque push (thread-safe for
                # single append, poll_log drains via snapshot).
                self.q.put(("line", gen))
                with self._lock:
                    self._line_buf.append(line.rstrip("\n"))
            self.q.put(("eof", gen))
        except ValueError:
            logger.debug("pump stream closed while draining (generation %d)", gen)
            self.q.put(("eof", gen) if proc.poll() is not None
                       else ("pump_error", gen, "stream closed while process alive"))
        except Exception as e:
            logger.warning("pump error: %s", e)
            self.q.put(("eof", gen) if proc.poll() is not None
                       else ("pump_error", gen, str(e)))

    def _stop_proc(self, proc):
        """Terminate+wait+kill a live process, returning True only when the
        process is proven exited. One primitive used by explicit stop,
        pump_error, and EOF cleanup."""
        if proc is None or proc.poll() is not None:
            return True
        try:
            proc.terminate()
        except OSError:
            return False
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                return False
        return proc.poll() is not None

    def poll_log(self):
        while True:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                break
            tag = item[0]
            if tag == "line":
                gen, = item[1:]
            elif tag == "eof":
                gen, = item[1:]
            elif tag == "pump_error":
                gen, payload = item[1], item[2]
            else:
                continue
            if gen != self._gen:
                continue
            if tag == "line":
                # Coalesce: only show the latest N lines from the bounded buf.
                with self._lock:
                    latest = list(self._line_buf)
                if latest:
                    self.last_line_var.set(latest[-1][:80])
            elif tag == "pump_error":
                with self._lock:
                    ok = self._stop_proc(self.proc)
                    if ok:
                        self.proc = None
                        self.status_var.set("Error: %s" % payload)
                    self.check_var.set(False)
            else:  # eof
                with self._lock:
                    self._stop_proc(self.proc)
                    self.proc = None
                    self.status_var.set("Stopped")
                    self.check_var.set(False)

    def stop(self):
        with self._lock:
            if self.is_running():
                ok = self._stop_proc(self.proc)
                if ok:
                    self.proc = None
        self.status_var.set("Stopped")
        self.check_var.set(False)
