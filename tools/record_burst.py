import datetime
import os
import sys
import time

import cv2

import capture


def main(duration_sec=14.0, interval_sec=0.5, fmt="png", out_subdir="burst_death"):
    out_dir = os.path.join(os.path.dirname(__file__), "templates", out_subdir)
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, f))

    hwnd = capture.find_window()
    start = time.time()
    with open(os.path.join(out_dir, "_meta.txt"), "w") as meta:
        meta.write(f"start_epoch={start}\n")
        meta.write(f"start_iso={datetime.datetime.fromtimestamp(start).isoformat()}\n")

    n = 0
    while time.time() - start < duration_sec:
        if not capture.is_minimized(hwnd):
            img = capture.grab(hwnd)
            ts = time.time() - start
            path = os.path.join(out_dir, f"frame_{n:04d}_{ts:06.1f}s.{fmt}")
            if fmt == "jpg":
                cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            else:
                cv2.imwrite(path, img)
            n += 1
        time.sleep(interval_sec)
    print(f"saved {n} frames to {out_dir}")


if __name__ == "__main__":
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 14.0
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
    fmt = sys.argv[3] if len(sys.argv) > 3 else "png"
    out_subdir = sys.argv[4] if len(sys.argv) > 4 else "burst_death"
    main(dur, interval, fmt, out_subdir)
