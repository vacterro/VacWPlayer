import ctypes
import logging
import win32con
import win32gui
import win32process
import win32ui
import numpy as np

logger = logging.getLogger(__name__)

PW_CLIENTONLY = 1
PW_RENDERFULLCONTENT = 2


def find_window(title: str = "HD-Player") -> int:
    hwnd = win32gui.FindWindow(None, title)
    if not hwnd:
        raise RuntimeError(f"window not found: {title}")
    return hwnd


def window_pid(hwnd: int) -> int:
    """Return the process id that owns `hwnd` (0 if it cannot be determined)."""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except Exception:
        return 0


def window_title(hwnd: int) -> str:
    """Return the current text of `hwnd`'s title bar ('' on failure)."""
    try:
        return win32gui.GetWindowText(hwnd)
    except Exception:
        return ""


def window_identity(hwnd: int):
    """Return (title, pid) for `hwnd`; either may be empty/0 on failure."""
    return window_title(hwnd), window_pid(hwnd)


def find_window_identity(title: str = "HD-Player"):
    """Like find_window() but also returns the owning process id, so callers can
    bind the acquired handle to a stable identity (title + PID) and later detect
    when the numeric handle has been reclaimed by a *different* window (W2-002).

    CORE-014: an unobservable PID (<= 0) is UNKNOWN, never a valid identity.
    Acquisition fails loudly (RuntimeError) rather than yielding a title-only
    identity the caller would believe carries a PID invariant."""
    hwnd = find_window(title)
    pid = window_pid(hwnd)
    if not pid:
        raise RuntimeError(f"cannot determine owning pid for window: {title}")
    return hwnd, pid


def is_same_window(hwnd: int, expected_title: str, expected_pid: int) -> bool:
    """W2-002: True ONLY when `hwnd` is a live window whose title AND owning pid
    still match the captured identity.

    ``win32gui.IsWindow`` alone is not enough: when the target window is
    destroyed its numeric handle can be reclaimed by an unrelated foreign
    window, which still passes IsWindow. Binding to title+PID catches that reuse
    and forces a re-acquire instead of scanning/clicking the wrong window.

    CORE-014: a zero/unknown expected PID or a zero current PID is never proof
    of sameness - two failed observations must not compare equal."""
    if not hwnd or not expected_pid or not win32gui.IsWindow(hwnd):
        return False
    try:
        pid = window_pid(hwnd)
        if not pid:
            return False  # UNKNOWN current PID: not proof of sameness
        return (window_title(hwnd) == expected_title
                and pid == expected_pid)
    except Exception:
        return False


def is_minimized(hwnd: int) -> bool:
    return win32gui.IsIconic(hwnd)


def is_foreground(hwnd: int) -> bool:
    """True when `hwnd` is the foreground window - the only state where the
    cheap BitBlt-from-screen grab_region is provably occlusion-safe (T-146).
    Anything else goes through PrintWindow instead of risking foreign pixels."""
    try:
        return win32gui.GetForegroundWindow() == hwnd
    except Exception as e:
        logger.debug("is_foreground(%r) failed: %s", hwnd, e)
        return False


def get_client_size(hwnd: int) -> tuple[int, int]:
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    return right - left, bottom - top


def _printwindow_bgra(hwnd: int) -> np.ndarray:
    """PrintWindow the client area and return the raw 4-channel BGRA frame
    (no alpha drop, no BGR conversion). Region-only callers crop this FIRST and
    convert just the crop - T-W2-PERF-004's win over converting the whole frame.

    Every GDI handle is acquired inside the same try whose finally releases
    only what was actually created (T-147)."""
    w, h = get_client_size(hwnd)
    if w <= 0 or h <= 0:
        raise RuntimeError("PrintWindow rejected: zero-size client area")
    hwnd_dc = mfc_dc = save_dc = bitmap = None
    try:
        # PW_CLIENTONLY matters for windows with a title bar/border (anything but
        # BlueStacks' current borderless-fullscreen mode): without it, PrintWindow
        # renders starting from the window's top-left (chrome included) into a
        # client-sized bitmap, silently shifting every pixel up by the chrome
        # height - which then throws off any click coordinates read from the
        # image.
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bitmap)

        ok = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_CLIENTONLY | PW_RENDERFULLCONTENT)

        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)
        img = np.frombuffer(bmpstr, dtype=np.uint8).reshape((bmpinfo["bmHeight"], bmpinfo["bmWidth"], 4))
        img = np.ascontiguousarray(img)  # keep 4 channels (BGRA)
    finally:
        if bitmap is not None:
            try:
                win32gui.DeleteObject(bitmap.GetHandle())
            except Exception as e:
                logger.debug("DeleteObject(bitmap) failed: %s", e)
        if save_dc is not None:
            try:
                save_dc.DeleteDC()
            except Exception as e:
                logger.debug("save_dc.DeleteDC failed: %s", e)
        if mfc_dc is not None:
            try:
                mfc_dc.DeleteDC()
            except Exception as e:
                logger.debug("mfc_dc.DeleteDC failed: %s", e)
        if hwnd_dc is not None:
            try:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception as e:
                logger.debug("ReleaseDC(%r) failed: %s", hwnd, e)

    if not ok:
        raise RuntimeError("PrintWindow failed (window minimized?)")
    return img


def grab_rgba(hwnd: int) -> np.ndarray:
    """Capture window client area via PrintWindow, returned as raw 4-channel BGRA.

    Identical occlusion-safety to grab(); provided so region-only consumers can
    crop FIRST and convert only the crop (T-W2-PERF-004), avoiding a full-frame
    BGR->gray conversion they don't need."""
    return _printwindow_bgra(hwnd)


def grab(hwnd: int) -> np.ndarray:
    """Capture window client area via PrintWindow. Works even if occluded by other windows.

    Every GDI handle is acquired inside the same try whose finally releases
    only what was actually created (T-147): a throw between GetWindowDC and
    SelectObject can no longer leak the already-acquired DCs, and a
    zero-size client is rejected before anything is allocated.

    T-W2-PERF-004: implemented as grab_rgba() with the alpha channel dropped, so
    the expensive GDI/PrintWindow work lives in exactly one place."""
    return np.ascontiguousarray(grab_rgba(hwnd)[:, :, :3])  # drop alpha -> BGR for OpenCV


def grab_region(hwnd: int, region: list[int]) -> np.ndarray:
    """Cheap capture of a small client-space region via BitBlt-from-screen.

    Far lighter than grab()'s PrintWindow (which makes the source app
    re-render its *entire* surface no matter how small the destination
    bitmap is) - this only ever touches the handful of pixels the caller
    asks for, which is what makes polling at a few Hz not show up on a CPU
    graph. Trade-off: unlike PrintWindow, a real screen-region BitBlt shows
    whatever is topmost on the desktop, so if another window ever overlaps
    exactly this region the read will be wrong. Only occlusion-safe while the
    window is foreground (T-146) - callers that may run with the window
    behind another one must use grab_client_region instead.
    """
    x0, y0, x1, y1 = region
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        raise RuntimeError("grab_region rejected: non-positive region size")
    screen_x, screen_y = win32gui.ClientToScreen(hwnd, (x0, y0))

    desktop_dc = win32gui.GetWindowDC(0)
    img_dc = mem_dc = bitmap = None
    try:
        img_dc = win32ui.CreateDCFromHandle(desktop_dc)
        mem_dc = img_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(img_dc, w, h)
        mem_dc.SelectObject(bitmap)
        mem_dc.BitBlt((0, 0), (w, h), img_dc, (screen_x, screen_y), win32con.SRCCOPY)

        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)
        img = np.frombuffer(bmpstr, dtype=np.uint8).reshape((bmpinfo["bmHeight"], bmpinfo["bmWidth"], 4))
        img = np.ascontiguousarray(img[:, :, :3])
        return img
    finally:
        if bitmap:
            try:
                win32gui.DeleteObject(bitmap.GetHandle())
            except Exception as e:
                logger.debug("DeleteObject(bitmap) failed: %s", e)
        if mem_dc:
            mem_dc.DeleteDC()
        if img_dc:
            img_dc.DeleteDC()
        win32gui.ReleaseDC(0, desktop_dc)


def grab_client_region(hwnd: int, region: list[int]) -> np.ndarray:
    """Occlusion-safe region read (T-146): PrintWindow the whole client area,
    then crop the client-space `region` from it. Never reads foreign pixels
    even when another window overlaps the target - at the cost of a full
    PrintWindow re-render. Use it whenever the window may not be foreground
    (the accept/surrender background contract).

    T-W2-PERF-004: crops the raw BGRA frame BEFORE materializing a BGR copy, so
    only the cropped pixels are converted - the full-frame numpy copy is gone."""
    img = grab_rgba(hwnd)
    x0, y0, x1, y1 = region
    return np.ascontiguousarray(img[y0:y1, x0:x1, :3])  # crop-first, then BGR


if __name__ == "__main__":
    import cv2
    import os

    hwnd = find_window()
    print("minimized:", is_minimized(hwnd))
    img = grab(hwnd)
    print("shape:", img.shape)
    out = os.path.join(os.path.dirname(__file__), "templates", "capture_test.png")
    cv2.imwrite(out, img)
    print("saved:", out)
