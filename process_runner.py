import logging
import os
import threading
import subprocess
import queue
import sys


logger = logging.getLogger(__name__)

BASE = os.path.dirname(__file__)
PYTHON = sys.executable


class ProcessRunner:
    """Manages a long-lived Python subprocess with stdout pump.

    Thread-safe: a generation counter isolates pump threads from previous
    start() calls, so a stale pump can never consume the NEW process's stream
    or overwrite current UI state. The Popen object is captured locally and
    stored on the instance only after a successful spawn.

    PERF-001: line output uses a single-slot overwrite (not a queue of
    events). The pump thread atomically overwrites _latest_line under
    lock; poll_log() consumes it once per tick. The queue only carries
    terminal/control events (eof, pump_error). This gives O(1) memory and
    O(1) poll cost regardless of line count.
    """

    def __init__(self, script_name, status_var, last_line_var, check_var):
        self.script_path = os.path.join(BASE, script_name)
        self.status_var = status_var
        self.last_line_var = last_line_var
        self.check_var = check_var
        self.proc = None
        # PERF-001: only terminal/control events (eof, pump_error) use the queue.
        self.q = queue.Queue()
        # PERF-001: single-slot latest line: (gen, text) or None.
        self._latest_line = None  # (gen, text) under _lock
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
            # PERF-001: clear stale line slot on new generation so old-output
            # never surfaces after restart.
            self._latest_line = None
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
                # PERF-001: atomically overwrite the single-slot latest line.
                # poll_log consumes it once per tick; intermediate lines are
                # discarded. No queue event is sent for line output.
                text = line.rstrip("\n")
                with self._lock:
                    self._latest_line = (gen, text)
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
            # W2-008: the child may have exited naturally between the initial
            # poll and TerminateProcess. A non-destructive re-poll proves it;
            # only a still-live or genuinely-unknown process is a failure.
            try:
                if proc.poll() is not None:
                    return True
            except Exception:
                return False
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
        # PERF-001: consume at most one terminal event AND one line slot.
        # Terminal events are processed first (eof/pump_error are rare and
        # lossless). Then atomically consume the latest line once.
        try:
            item = self.q.get_nowait()
        except queue.Empty:
            item = None
        if item is not None:
            tag = item[0]
            if tag == "eof":
                gen, = item[1:]
            elif tag == "pump_error":
                gen, payload = item[1], item[2]
            else:
                gen = None
            if gen is not None and gen == self._gen:
                if tag == "pump_error":
                    # CORE-009: only flip the monitor checkbox to OFF when the
                    # child is PROVEN exited. If _stop_proc failed the child is
                    # still live - reporting monitor OFF would hide a running
                    # process, and a caller persisting monitor_enabled=False on
                    # that signal would orphan it (W2-006).
                    with self._lock:
                        ok = self._stop_proc(self.proc)
                        if ok:
                            self.proc = None
                            self.status_var.set("Error: %s" % payload)
                            self.check_var.set(False)
                else:  # eof
                    with self._lock:
                        ok = self._stop_proc(self.proc)
                        if ok:
                            self.proc = None
                            self.status_var.set("Stopped")
                            self.check_var.set(False)
        # PERF-001: atomically consume the latest line slot (at most once).
        with self._lock:
            slot = self._latest_line
            self._latest_line = None
        if slot is not None:
            slot_gen, slot_text = slot
            if slot_gen == self._gen:
                self.last_line_var.set(slot_text[:80])

    def stop(self):
        """Stop the child process. Returns True when proven exited, False when
        stop failed and a live child is retained.

        W2-006: callers must check the return value before persisting
        monitor_enabled=False - a failed stop means the child is still live.
        """
        with self._lock:
            if self.is_running():
                ok = self._stop_proc(self.proc)
                if ok:
                    self.proc = None
                    self.status_var.set("Stopped")
                    self.check_var.set(False)
                    return True
                # stop failed: proc retained, status unchanged. Do NOT flip the
                # monitor checkbox OFF here - the child is still live, so
                # reporting monitor OFF would hide a running process that callers
                # would then orphan (CORE-009 / W2-006). The caller sees False
                # from stop() and must not persist monitor_enabled=False.
                return False
            else:
                # Already exited: clear any stale reference.
                self.proc = None
        self.status_var.set("Stopped")
        self.check_var.set(False)
        return True
