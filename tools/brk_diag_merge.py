#!/usr/bin/env python3
"""
VOP Diagnostic Tool:    brk_diag_merge.py
Description:            Standalone CLI harness for diagnosing the BRK
                        per-bracket merger against a fixed set of captured
                        DNGs. No camera, no engine, no GUI - just decode
                        and merge.

Usage from the VOP repo root:

    ./venv/bin/python tools/brk_diag_merge.py \\
        path/to/b0.dng path/to/b1.dng path/to/b2.dng \\
        --output merged.tif

The DNGs must be in PEAK -> MIDDLE -> DEEPEST order, matching the order
BRK captures them in (bracket index 0 = peak, N-1 = deepest). The merger
relies on this ordering via its is_first / is_last per-bracket flags.

This script reuses the project's REAL decode and merge modules:
    color_utils.dng_to_uint16_rgb   - the engine's DNG-to-uint16 path
    brk_sequencer.compute_brackets  - the engine's bracket spec builder
    brk_merger.merge                - the engine's per-pixel merge math

Any change to those modules propagates here automatically. That's the
whole point - the harness tests what the engine actually runs, not a
reimplementation.

When iterating on brk_merger.py, run this script after each change to
verify the merged output against the known input set. Much faster than
deploying to the Pi and triggering a real capture.
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


import argparse
import os
import sys

# Add ../modules to sys.path so we can import the project's modules.
# The tools/ directory is one level below the repo root; modules/ is a
# sibling of tools/. Done this way (rather than installing the project
# as a package) because the project isn't packaged yet, and this script
# is diagnostic - it doesn't need to be importable from elsewhere.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO_ROOT, 'modules'))

import numpy as np
import cv2

# Project modules. These imports must succeed for the harness to run.
# If any of them fails the harness halts with a clear error - we don't
# want to silently fall back to a reimplemented merger.
import color_utils as cutil
import brk_sequencer
import brk_merger


def parse_args():
    """
    Parse CLI arguments. Three positional DNG paths in peak->deepest
    order, an optional output path, and optional overrides for the
    sequencer's bracket count and stops parameters.
    """
    parser = argparse.ArgumentParser(
        description="Diagnose the BRK merger against fixed DNG inputs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'dngs',
        nargs='+',
        help='Per-bracket DNG paths in peak -> deepest order. Number of '
             'DNGs must match --bracket-count (default 3).',
    )
    parser.add_argument(
        '--output', '-o',
        default='brk_diag_merged.tif',
        help='Output TIFF path (default: brk_diag_merged.tif in CWD). '
             'Written as 16bpc RGB - same format as CamMag/ latents.',
    )
    parser.add_argument(
        '--bracket-count', type=int, default=3,
        help='Number of brackets the sequencer should plan (default 3). '
             'Must match len(dngs).',
    )
    parser.add_argument(
        '--bracket-stops', type=float, default=1.0,
        help='Bracket-spacing in stops (default 1.0). The sequencer uses '
             'this to compute slice_low/slice_high for each bracket.',
    )
    parser.add_argument(
        '--static-dir', default=os.path.join(REPO_ROOT, 'static'),
        help='Path to the runtime static/ dir (for the hot-pixel defect '
             'map). Defaults to ../static relative to this script. If the '
             'defect map is missing, the decode skips that step.',
    )
    parser.add_argument(
        '--t-peak', type=float, default=0.75,
        help='Peak exposure time in seconds. Only used by the sequencer '
             'to populate BracketSpec.exposure_s (the merger does not '
             "read this field). Default matches the project's typical "
             'calibration value.',
    )

    args = parser.parse_args()

    # Sanity: DNG count vs --bracket-count. Strict equality - if the
    # user passes the wrong number we want a clear error, not a confusing
    # downstream failure.
    if len(args.dngs) != args.bracket_count:
        parser.error(
            f"Got {len(args.dngs)} DNG paths but --bracket-count is "
            f"{args.bracket_count}. They must match."
        )

    return args


def log(msg):
    """
    Minimal logging. Single stream (stdout). Prefixed with [DIAG] so
    that if this output gets mixed with other tool output (e.g. when
    invoked from a wrapper) it's clearly tagged.
    """
    print(f"[DIAG] {msg}", flush=True)


def main():
    args = parse_args()

    # ---- Step 1: build the bracket spec list via the real sequencer ----
    #
    # The sequencer returns BracketSpec NamedTuples in PEAK-FIRST order
    # (index 0 = peak, index N-1 = deepest). The DNG list order on the
    # command line MUST match. We do not re-order or guess.
    #
    # Why use the real sequencer rather than hardcoding slices? Because
    # the slice math (slice_low_norm = s_top / 2^(bracket * stops),
    # etc.) lives in the sequencer module and is the system's source
    # of truth. If we hardcode slices here we'd silently drift away
    # from production behavior.
    log(f"Building bracket specs: count={args.bracket_count} "
        f"stops={args.bracket_stops} t_peak={args.t_peak}s")
    brackets = brk_sequencer.compute_brackets(
        bracket_count=args.bracket_count,
        bracket_stops=args.bracket_stops,
        t_peak_s=args.t_peak,
    )
    for b in brackets:
        log(f"  bracket {b.index}: "
            f"slice=[{b.slice_low_norm:.4f}, {b.slice_high_norm:.4f}] "
            f"exposure={b.exposure_s:.3f}s")

    # ---- Step 2: decode each DNG via the engine's real decode path ----
    #
    # cutil.dng_to_uint16_rgb does: rawpy.postprocess (linear, no auto
    # bright, 16bpc) -> hot pixel patch -> optional pedestal subtraction.
    # We pass black_clip=0.0 so the decode matches what execute_brk_
    # exposure feeds into the merger (BRK doesn't apply pedestal at
    # capture time - the merger's weighting handles noise-floor masking).
    #
    # Returns numpy.ndarray (H, W, 3) uint16 in RGB order. We collect
    # all three before merging.
    log(f"Decoding {len(args.dngs)} DNGs (static_dir={args.static_dir})")
    captures = []
    for i, path in enumerate(args.dngs):
        if not os.path.exists(path):
            log(f"  ERROR: DNG not found: {path}")
            return 2
        log(f"  decoding b{i}: {path}")
        arr = cutil.dng_to_uint16_rgb(
            buffer_file=path,
            static_dir=args.static_dir,
            black_clip=0.0,
        )
        if arr is None:
            log(f"  ERROR: dng_to_uint16_rgb returned None for {path}")
            return 2
        log(f"    shape={arr.shape} dtype={arr.dtype} "
            f"min={arr.min()} max={arr.max()} "
            f"mean={arr.mean():.0f}")
        captures.append(arr)

    # Quick sanity: bracket means should be monotonically NON-DECREASING
    # from peak to deepest. Deeper brackets remap a smaller source slice
    # to fill the screen, so their captures should be brighter on average.
    # If they aren't, the DNG order is probably wrong (b0 and b2 swapped).
    means = [c.mean() for c in captures]
    if not all(means[i] <= means[i+1] for i in range(len(means) - 1)):
        log("  WARNING: capture means are NOT monotonically increasing "
            "from peak to deepest. Are the DNGs in the right order?")
        log(f"           means: {[f'{m:.0f}' for m in means]}")

    # ---- Step 3: run the real merger ----
    #
    # brk_merger.merge(captures, brackets) -> uint16 (H, W, 3) in RGB
    # order. This is the function under test. Any output anomalies we
    # see come from THIS call (or its inputs, which we've already
    # logged).
    log(f"Merging {len(captures)} brackets...")
    merged = brk_merger.merge(captures, brackets)
    log(f"  merged: shape={merged.shape} dtype={merged.dtype} "
        f"min={merged.min()} max={merged.max()}")
    r, g, b = merged[:,:,0], merged[:,:,1], merged[:,:,2]
    log(f"  R: min={r.min():5d} max={r.max():5d} mean={r.mean():.0f}")
    log(f"  G: min={g.min():5d} max={g.max():5d} mean={g.mean():.0f}")
    log(f"  B: min={b.min():5d} max={b.max():5d} mean={b.mean():.0f}")

    # ---- Step 4: write the merged TIFF ----
    #
    # cv2 expects BGR order on imwrite. The merger returns RGB (matching
    # what the engine's _finalize_brk_capture also gets). We convert
    # to BGR here for the disk write, same as the engine does.
    out_bgr = cv2.cvtColor(merged, cv2.COLOR_RGB2BGR)

    # ZIP-compressed 16bpc TIFF. Compression flag 8 = ADOBE_DEFLATE (ZIP).
    # Matches the project's standard tiff_compression='zip' setting.
    ok = cv2.imwrite(
        args.output,
        out_bgr,
        [cv2.IMWRITE_TIFF_COMPRESSION, 8],
    )
    if not ok:
        log(f"  ERROR: failed to write {args.output}")
        return 3

    log(f"Done. Wrote {args.output}")
    return 0


if __name__ == '__main__':
    sys.exit(main())