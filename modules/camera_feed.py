"""
VOP Module:     camera_feed.py
Description:    Live MJPEG preview feed from the IMX477 for the
                Calibration page's framing / focus tool (issue #198).

                Unlike camera_hardware.trigger_capture (one rpicam-still
                per exposure), this runs rpicam-vid CONTINUOUSLY and
                relays its MJPEG output to the browser over HTTP as
                multipart/x-mixed-replace. The browser shows it with a
                plain <img src="/calibration_feed"> - no JS decode, no
                websockets, no extra pip deps. MJPEG is intra-only (every
                frame is a full JPEG) so end-to-end latency is just
                encode + LAN hop: ideal for responsive focus/alignment.

                CAMERA IS SINGLE-OWNER. rpicam-vid (this feed) and
                rpicam-still (every capture/preview/measurement) cannot
                hold the sensor at the same time. The feed MUST be stopped
                before any capture. vop.py enforces this in dispatch_engine.
"""

#
###########################################################################
#
#                                   VOP
#                       Copyright (C) 2025  jmalmsten
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU Affero General Public License as
#     published by the Free Software Foundation, either version 3 of the
#     License, or (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful, but
#     WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#     Affero General Public License for more details.
#
#     You should have received a copy of the GNU Affero General Public
#     License along with this program.  If not, see
#     <http://www.gnu.org/licenses/>.
#
#     Source code for this application can be found at
#     https://codeberg.org/jmalmsten-com/VOP
#
###########################################################################


import subprocess
import threading

# ---------------------------------------------------------
# FEED TUNABLES
# ---------------------------------------------------------
# Full-sensor 4:3 (2028x1520 = HQ cam, 2x2-binned full frame). We want
# the WHOLE sensor in the feed so the framing overlay shows the real
# sensor edges, and high enough resolution that 1:1 zoom is sharp enough
# to judge focus. MJPEG at this size is well within the Pi 4 encoder +
# gigabit budget (the old align tool ran 2028x1520 mjpeg at 30fps).
FEED_WIDTH  = 2028
FEED_HEIGHT = 1520

# --mode forces the full-frame sensor read. Without it, libcamera picks
# a sensor mode from --width/--height and can land on a CROPPED mode that
# doesn't see the whole sensor - which would make the framing overlay lie
# about where the sensor edges are. 2028:1520:12:P = full frame, 12-bit,
# packed. Same reasoning as the old vop_setup_align.py.
FEED_SENSOR_MODE = "2028:1520:12:P"

# Frame rate. Alignment/focus is a near-static visual task, so we trade
# motion smoothness for bitrate headroom (more bits per frame = sharper
# detail at the same bandwidth). 8-30 are all acceptable per the issue;
# 20 is a comfortable middle that still feels live when nudging the rig.
FEED_FPS = 20

# JPEG frame delimiters in the MJPEG byte stream. Every JPEG starts with
# SOI (FF D8) and ends with EOI (FF D9). We scan rpicam-vid's stdout for
# these to slice out complete frames. EOI only ever appears as a real
# marker (in-data FF bytes are byte-stuffed as FF 00), so this is reliable
# for a preview feed.
_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"

# ---------------------------------------------------------
# MODULE STATE (one shared feed for all browser clients)
# ---------------------------------------------------------
# Only ONE rpicam-vid runs no matter how many tabs are open; every client
# reads the same latest-frame buffer. _lock guards the process lifecycle
# (start/stop); _cond signals waiting client generators when a fresh frame
# lands, so they sleep instead of busy-waiting between frames.
_proc = None            # the rpicam-vid Popen, or None when stopped
_reader_thread = None   # background thread draining rpicam-vid stdout
_latest_frame = None    # most recent complete JPEG (bytes), or None
_frame_seq = 0          # increments per frame so generators detect "new"
_lock = threading.Lock()
_cond = threading.Condition()


def is_running():
    """True if the feed subprocess is currently live."""
    with _lock:
        return _proc is not None and _proc.poll() is None


def start_feed():
    """
    Start the continuous MJPEG feed if it isn't already running.
    Idempotent: calling while running is a no-op, so routes can call it
    freely. Returns True once the feed is running.

    NOTE: the caller must ensure no rpicam-still is in flight (engine
    idle) - the sensor is single-owner. See the module docstring.
    """
    global _proc, _reader_thread, _latest_frame
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return True  # already running

        # Clear any stale frame from a previous run so a freshly-connected
        # client never sees an old image presented as "live".
        _latest_frame = None

        # No sudo: the engine's trigger_capture runs rpicam-still without
        # sudo, so the deployed user is already in the 'video' group.
        # Matching that here keeps permissions consistent.
        cmd = [
            "rpicam-vid",
            "-t", "0",                  # run forever (until we terminate it)
            "-n",                       # no preview window -> no DRM conflict with the engine
            "--mode", FEED_SENSOR_MODE, # force full-sensor read (see above)
            "--width",  str(FEED_WIDTH),
            "--height", str(FEED_HEIGHT),
            "--framerate", str(FEED_FPS),
            "--codec", "mjpeg",
            "-o", "-",                  # MJPEG to stdout; reader thread drains it
        ]

        # bufsize=0 keeps latency low (no Python-side buffering on the
        # binary stream). stderr is discarded - rpicam-vid is chatty and
        # we don't want it flooding the journal during framing sessions.
        _proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
        )

        _reader_thread = threading.Thread(
            target=_reader_loop, args=(_proc,), daemon=True
        )
        _reader_thread.start()
        return True


def stop_feed():
    """
    Stop the feed and release the camera. Idempotent. Safe (and cheap)
    to call right before kicking off any capture/measurement, even when
    the feed isn't running.
    """
    global _proc
    with _lock:
        proc = _proc
        _proc = None  # tells the reader loop and is_running() we're done
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
    # Wake any client generators so they exit their wait and close the
    # HTTP response cleanly instead of hanging for a frame that won't come.
    with _cond:
        _cond.notify_all()


def _reader_loop(proc):
    """
    Background thread: drains rpicam-vid stdout, slices the MJPEG byte
    stream into complete JPEGs on SOI/EOI boundaries, and publishes each
    finished frame, notifying waiting clients.
    """
    # _proc must be declared global here too: the finally block below
    # assigns `_proc = None`, and a single assignment anywhere in the
    # function makes Python treat _proc as local THROUGHOUT - which is
    # what made the earlier `if _proc is not proc:` read raise
    # UnboundLocalError. Listing it here keeps both the reads and that
    # assignment pointing at the module global.
    global _proc, _latest_frame, _frame_seq
    buf = bytearray()
    try:
        while True:
            # Bail if stop_feed() swapped _proc out, or the process died.
            with _lock:
                if _proc is not proc:
                    break
            chunk = proc.stdout.read(65536)
            if not chunk:
                break  # EOF: process exited (cable yanked, crash, etc.)
            buf.extend(chunk)

            # Extract EVERY complete frame currently buffered. We loop
            # because one read can contain several frames; we only ever
            # publish whole JPEGs.
            while True:
                start = buf.find(_SOI)
                if start < 0:
                    break
                end = buf.find(_EOI, start + 2)
                if end < 0:
                    break          # tail is a partial frame; wait for more
                end += 2           # include the 2 EOI bytes
                frame = bytes(buf[start:end])
                del buf[:end]      # drop up to and including this frame

                with _cond:
                    _latest_frame = frame
                    _frame_seq += 1
                    _cond.notify_all()
    finally:
        # If rpicam-vid exited on its own, make sure is_running() reports
        # false and any clients get released.
        with _lock:
            if _proc is proc:
                _proc = None
        with _cond:
            _cond.notify_all()


def frames():
    """
    Generator for Flask's multipart/x-mixed-replace response. Yields one
    MJPEG part per NEW frame, sleeping (not busy-waiting) on the Condition
    between frames. Exits when the feed stops or the client disconnects
    (Flask closes the generator).
    """
    last_seen = -1
    boundary = b"--vopframe"
    while True:
        with _cond:
            # Sleep until a frame newer than the last we sent arrives. The
            # 1s timeout lets us re-check is_running() so a stopped feed
            # doesn't leave us blocked forever.
            if _frame_seq == last_seen:
                _cond.wait(timeout=1.0)
            frame = _latest_frame
            seq = _frame_seq

        # Stopped with nothing new to send -> end the response.
        if not is_running() and (frame is None or seq == last_seen):
            break
        # Timed out with no new frame -> loop and re-check.
        if seq == last_seen or frame is None:
            continue

        last_seen = seq
        yield (
            boundary + b"\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
            + frame + b"\r\n"
        )