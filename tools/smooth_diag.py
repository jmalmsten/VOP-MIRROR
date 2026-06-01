"""
VOP tool: tools/smooth_diag.py
Description:    Off-Pi diagnostic for SSS smooth interpolation (issue #155).

               Builds a real interpolator.Timeline from a synthetic SSS job
               and probes the velocity of the master position just before and
               just after each interior keyframe. Classifies each keyframe as:

                 SMOOTH  - velocity continuous AND non-zero: motion flows
                           through the keyframe (the fixed behaviour).
                 STOPPED - velocity ~0 on both sides: motion halts at the
                           keyframe. Correct ONLY at a genuine rest point
                           (true endpoint, a motion apex, or a corner).
                 KINK    - velocity differs across the keyframe: a hard angle.

               Reuses the real project module - no reimplementation - so what
               it reports is what the engine will actually do.

               Run from the VOP repo root:
                   ./venv/bin/python tools/smooth_diag.py
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

import os
import sys
import numpy as np

# Make the project root importable when run as ./venv/bin/python tools/smooth_diag.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

from modules.interpolator import Timeline


def make_job(corner_at_kf3=False):
    """4-keyframe SSS job. Master X traces 0 -> 2 -> 0 -> 1 with deliberately
    NON-UNIFORM frame spacing (0, 10, 15, 30) and a direction reversal at
    keyframe 3 (frame 15) - the spot where U-vs-V behaviour is visible.
    kf3's corner override is toggled by the argument."""
    return {
        'smear_mode': 'SSS',
        'sss_f1': '0',  'sss_m1': 'S', 'sss_crn1': False,          'sss_p1': '0,0,-5',
        'sss_f2': '10', 'sss_m2': 'S', 'sss_crn2': False,          'sss_p2': '2,0,-5',
        'sss_f3': '15', 'sss_m3': 'S', 'sss_crn3': corner_at_kf3,  'sss_p3': '0,0,-5',
        'sss_f4': '30', 'sss_m4': 'S', 'sss_crn4': False,          'sss_p4': '1,0,-5',
    }


def classify(v_in, v_out, vtol=2e-2):
    stopped = abs(v_in) < vtol and abs(v_out) < vtol
    kink = abs(v_in - v_out) > vtol
    if stopped:
        return "STOPPED"
    if kink:
        return "KINK"
    return "SMOOTH"


def probe(tl, label, interior_frames):
    print(f"\n=== {label} ===")
    print(f"{'kf frame':>9} | {'v_in':>10} | {'v_out':>10} | {'verdict':>9}")
    eps = 1e-3
    x = lambda t: tl.get_state(t)['p'][0]   # X component of master position
    for f in interior_frames:
        v_in = (x(f) - x(f - eps)) / eps
        v_out = (x(f + eps) - x(f)) / eps
        print(f"{f:>9.1f} | {v_in:>10.4f} | {v_out:>10.4f} | {classify(v_in, v_out):>9}")


def main():
    interior = (10.0, 15.0)

    tl_smooth = Timeline(make_job(corner_at_kf3=False))
    probe(tl_smooth, "smooth, no corner (f=15 reversal should be SMOOTH; "
                     "f=10 apex legitimately STOPPED)", interior)

    tl_corner = Timeline(make_job(corner_at_kf3=True))
    probe(tl_corner, "corner override at f=15 (should be STOPPED there)", interior)

    print("\n=== keyframe pass-through (no corner) ===")
    for f, want in [(10.0, 2.0), (15.0, 0.0)]:
        got = tl_smooth.get_state(f)['p'][0]
        ok = "OK" if abs(got - want) < 1e-6 else "MISS"
        print(f"  f={f:>5.1f}: want X={want}, got X={got:+.6f}  {ok}")

    print("\n=== linear-segment regression (kf1 set to 'L', f=0..10 straight) ===")
    jobL = make_job()
    jobL['sss_m1'] = 'L'
    tlL = Timeline(jobL)
    for t in (0.0, 2.5, 5.0, 7.5, 10.0):
        got = tlL.get_state(t)['p'][0]
        want = (t / 10.0) * 2.0
        ok = "OK" if abs(got - want) < 1e-4 else "MISS"
        print(f"  t={t:>5.1f}: got {got:+.4f}  want {want:+.4f}  {ok}")


if __name__ == "__main__":
    main()
