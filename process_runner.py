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
            # Reaching here means proc is None or a DEAD old child. Drop the
            # stale reference now so a failed spawn below leaves proc = None,
            # never a pointer to the dead process (T-171).
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
        # `proc` is the captured child from THIS generation - never reads
        # self.proc, so a restarted process's stream cannot be drained by a
        # leftover pump from an older start().
        #
        # T-173: a stream failure is NOT proof the child exited. Only a clean
        # EOF (or a stream failure when the child is already gone) may become
        # "eof". A stream failure while the child is STILL ALIVE becomes
        # "pump_error" - poll_log then deliberately terminates it instead of
        # marking Stopped with a live process running untracked.
        try:
            for line in proc.stdout:
                self.q.put(("line", gen, line.rstrip("\n")))
            self.q.put(("eof", gen))
        except ValueError:
            logger.debug("pump stream closed while draining (generation %d)", gen)
            self.q.put(("eof", gen) if proc.poll() is not None
                       else ("pump_error", gen, "stream closed while process alive"))
        except Exception as e:
            logger.warning("pump error: %s", e)
            self.q.put(("eof", gen) if proc.poll() is not None
                       else ("pump_error", gen, str(e)))

    def _terminate_captured(self):
        """Deliberately terminate the captured child when its stream died but
        the process is still alive - never leave a live child untracked."""
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        except OSError as e:
            logger.warning("terminate of captured child failed: %s", e)

    def poll_log(self):
        while True:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                break
            tag = item[0]
            if tag == "line":
                gen, payload = item[1], item[2]
            elif tag == "eof":
                gen, payload = item[1], None
            elif tag == "pump_error":
                gen, payload = item[1], item[2]
            else:
                continue
            if gen != self._gen:
                # stale-generation event from an older pump: ignore entirely,
                # lines, eof and error markers alike.
                continue
            if tag == "line":
                self.last_line_var.set(payload[:80])
            elif tag == "pump_error":
                with self._lock:
                    self._terminate_captured()  # never orphan a live child
                    self.status_var.set("Error: %s" % payload)
                    self.check_var.set(False)
                    self.proc = None
            else:  # eof: stream ended - the child is gone or was terminated
                with self._lock:
                    self._terminate_captured()  # no-op if already exited
                    self.status_var.set("Stopped")
                    self.check_var.set(False)
                    self.proc = None

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
