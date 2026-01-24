"""
VOP Module:     vop_live_white_balance.py
Version:        v0.0.1
Description:    Live White Balance tuner. Displays gray on Pi monitor and 
                streams video to Fedora desktop with keyboard-adjustable gains.
Usage:          python3 vop_live_white_balance.py --desktop 1920.168.2.8
Controls:       UP/DOWN: Red Gain | LEFT/RIGHT: Blue Gain | Q: Quit
"""

import os
import subprocess
import argparse
import curses
import pygame

def run_tuner(desktop_ip):
    # --- Configuration ---
    red_gain = 2.40
    blue_gain = 2.20
    stream_proc = None

    # 1. Initialize Pygame for the Gray Target
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    os.environ["DISPLAY"] = ":0"
    pygame.init()
    screen = pygame.display.set_mode((1920, 1080), pygame.FULLSCREEN)
    screen.fill((128, 128, 128))
    pygame.display.update()

    def start_stream(r, b):
        nonlocal stream_proc
        if stream_proc:
            stream_proc.terminate()
            stream_proc.wait()
        
        # Using low-latency settings for the network pipe
        cmd = [
            "rpicam-vid", "-t", "0", "--inline",
            "-o", f"udp://{desktop_ip}:5000",
            "--width", "1280", "--height", "720",
            "--framerate", "30",
            "--awbgains", f"{r:.3f},{b:.3f}",
            "--denoise", "cdn_off",
            "-n" # No local preview
        ]
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 2. Curses Keyboard Listener
    def main(stdscr):
        nonlocal red_gain, blue_gain, stream_proc
        curses.curs_set(0)
        stdscr.nodelay(1)
        stdscr.timeout(100)
        
        stream_proc = start_stream(red_gain, blue_gain)

        while True:
            stdscr.clear()
            stdscr.addstr(0, 0, "VOP LIVE WB TUNER - v0.0.1")
            stdscr.addstr(1, 0, f"Target IP: {desktop_ip}")
            stdscr.addstr(3, 0, f"RED GAIN:  {red_gain:.3f}  (Use UP/DOWN)")
            stdscr.addstr(4, 0, f"BLUE GAIN: {blue_gain:.3f}  (Use LEFT/RIGHT)")
            stdscr.addstr(6, 0, "Press 'Q' to quit")
            stdscr.refresh()

            key = stdscr.getch()
            changed = False

            if key == ord('q'):
                break
            elif key == curses.KEY_UP:
                red_gain += 0.01
                changed = True
            elif key == curses.KEY_DOWN:
                red_gain -= 0.01
                changed = True
            elif key == curses.KEY_RIGHT:
                blue_gain += 0.01
                changed = True
            elif key == curses.KEY_LEFT:
                blue_gain -= 0.01
                changed = True

            if changed:
                red_gain = max(0.1, min(10.0, red_gain))
                blue_gain = max(0.1, min(10.0, blue_gain))
                stream_proc = start_stream(red_gain, blue_gain)

    try:
        curses.wrapper(main)
    finally:
        if stream_proc:
            stream_proc.terminate()
        pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop", default="192.168.2.8", help="IP of Fedora Desktop")
    args = parser.parse_args()
    run_tuner(args.desktop)