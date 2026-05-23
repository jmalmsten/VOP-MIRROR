"""
VOP Module:     brk_merger.py
Description:    Bracketed-exposure frame merger for BRK mode.

                Given N camera captures (uint16 (H,W,3) arrays)
                and the BracketSpec list they correspond to, this
                module produces one merged uint16 (H,W,3) array
                that reconstructs the source's full 16bpc range.

                Each capture encodes one slice of the source's
                tonal range, remapped to fill screen 0..255 at
                capture time. Inverting that remap turns each
                capture back into a "view" of its source slice
                in original 16bpc space. The N views are then
                combined with cross-fade weights that smooth out
                the seams between adjacent brackets - adjacent
                brackets cover overlapping source ranges (see
                OVERLAP_FRACTION below) and the overlap region
                is where the weighted blend lives.

                Algorithm shape:
                  1. For each bracket, un-remap its capture into
                     a "source-space view": a uint16 array where
                     each pixel holds an estimate of the original
                     source value, but only valid within that
                     bracket's slice range.
                  2. For each bracket, compute per-pixel weights
                     based on where the bracket's source-space
                     estimate falls relative to its slice's
                     overlap regions. Pixels deep in the slice
                     get weight 1.0; pixels in the overlap with
                     an adjacent bracket get fractional weights
                     that cross-fade to 0 at the slice edge.
                  3. Combine the per-bracket views as a weighted
                     average and emit the result as uint16.

                No screen-response gamma correction is applied
                here. The screen's actual response curve is a
                future calibration concern (cf. the LUT
                refinement noted in dre_sequencer.py). The
                overlap-blend smooths most of that nonlinearity
                out at the seam regions, which is the principal
                source of visible artifact.

                Numerical hygiene: all math runs in float32
                internally. The uint16 cast happens only at the
                very end, with a clip-to-range and a round-to-
                nearest. This avoids the silent wraparound that
                would occur if intermediate weighted sums went
                even momentarily above 65535 or below 0.
"""
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

import numpy as np


# Overlap fraction between adjacent brackets, in normalized source
# space, measured as a fraction of each slice's width.
#
# 0.2 = 20%. The peak bracket's slice extends 20% of its width down
# into the next bracket's territory, and the shadow bracket extends
# 20% of its width up into the peak's territory. So adjacent
# brackets see roughly 20% of overlapping source content, and the
# blend within that band cross-fades from "100% peak" at the
# peak-side edge to "100% shadow" at the shadow-side edge.
#
# Tuned during planning, not user-exposed - moving it requires
# code change. The 20% number is a "feels right" default with no
# strong theoretical justification; bumping it up makes seams
# softer but wastes more screen resolution on duplicated coverage,
# bumping it down sharpens transitions but risks visible banding
# at the boundaries when screen linearity is imperfect.
OVERLAP_FRACTION = 0.20


def merge(captures, brackets):
    """
    Merge N bracketed captures into one 16bpc latent array.

    Args:
        captures : list of numpy.ndarray, each dtype=uint16,
                   shape=(H, W, 3). One per bracket, in the
                   same order as `brackets`. Captures are the
                   raw camera output for each bracket - the
                   engine is responsible for any pre-processing
                   (noise crusher, hot pixel mapping, gel
                   adjustments) BEFORE handing them here.
                   That way the merger stays focused on the
                   bracket-merge math and doesn't duplicate
                   work the existing post-capture pipeline
                   already does.
        brackets : list of brk_sequencer.BracketSpec, same
                   length as captures, same ordering (peak-
                   first). The merger reads slice_low_norm
                   and slice_high_norm from each; other
                   fields (index, exposure_s) are not used
                   here but accepted unchanged for forward
                   compatibility.

    Returns:
        numpy.ndarray, dtype=uint16, shape=(H, W, 3). The
        merged frame in 16bpc source space. Suitable for
        writing as a latent TIFF via the existing
        process_and_stack_latent_image path (which already
        accepts uint16 arrays).

    Raises:
        ValueError if captures and brackets disagree in
        length, or if any capture has an unexpected dtype/
        shape. Fail-loud at the boundary so a misaligned
        engine-side data feed doesn't silently corrupt the
        output.
    """
    # Input validation. The engine should never call us with
    # mismatched inputs but defensive checking here means a
    # bug in the engine's bracket-collection loop surfaces
    # as a clear exception, not as a silently-wrong latent.
    if len(captures) != len(brackets):
        raise ValueError(
            f"brk_merger: captures count ({len(captures)}) does not "
            f"match brackets count ({len(brackets)})."
        )
    if len(captures) == 0:
        raise ValueError("brk_merger: at least one capture is required.")

    # All captures must agree on shape and dtype. Mixing
    # resolutions or pixel formats here is a programming bug,
    # not a recoverable condition.
    ref_shape = captures[0].shape
    for i, cap in enumerate(captures):
        if cap.dtype != np.uint16:
            raise ValueError(
                f"brk_merger: capture[{i}] has dtype {cap.dtype}, "
                f"expected uint16."
            )
        if cap.shape != ref_shape:
            raise ValueError(
                f"brk_merger: capture[{i}] shape {cap.shape} does "
                f"not match capture[0] shape {ref_shape}."
            )
        if cap.ndim != 3 or cap.shape[2] != 3:
            raise ValueError(
                f"brk_merger: capture[{i}] must be (H, W, 3), "
                f"got {cap.shape}."
            )

    H, W = ref_shape[:2]

    # Accumulators in float32. weight_sum tracks the total
    # weight applied at each pixel so we can divide at the end
    # for a proper weighted-average. value_sum accumulates
    # weight * source_estimate per bracket. Both stay in
    # float32 the whole way to avoid intermediate overflow on
    # the multiply-and-add.
    value_sum = np.zeros((H, W, 3), dtype=np.float32)
    weight_sum = np.zeros((H, W, 3), dtype=np.float32)

    # For each bracket: un-remap its capture into source space,
    # compute per-pixel weights based on slice geometry, and
    # add the weighted contribution to the accumulators.
    for bracket, capture in zip(brackets, captures):
        # ---- Un-remap the capture into source space ----
        #
        # The capture is uint16 because the camera produces
        # 12-16 bits depending on sensor; treating it as a
        # full-range capture and normalizing to [0..1] keeps
        # the math sensor-agnostic. The engine is responsible
        # for any sensor-saturation handling before this point.
        #
        # Per-pixel formula:
        #   source_estimate_norm = slice_low_norm
        #                        + (slice_high_norm - slice_low_norm)
        #                          * (capture_value / 65535)
        # i.e. the capture's 0..1 range maps linearly back
        # across [slice_low, slice_high].
        cap_norm = capture.astype(np.float32) / 65535.0
        slice_width = float(bracket.slice_high_norm - bracket.slice_low_norm)
        source_estimate = (
            float(bracket.slice_low_norm)
            + slice_width * cap_norm
        )

        # ---- Compute per-pixel weights ----
        #
        # Weight is 1.0 in the bracket's "core" region (the
        # middle of its slice, away from any overlap with
        # adjacent brackets). It tapers linearly to 0 across
        # the overlap region into adjacent brackets. The exact
        # taper shape doesn't matter much for the final
        # quality - linear is the simplest and behaves well
        # numerically. Tukey or raised-cosine windows would
        # also be reasonable choices if banding turns out
        # to be visible in practice (something to tune in a
        # future polish pass).
        #
        # Per-pixel weight formula, with a few cases:
        #   - For the peak bracket (index 0): no upper-edge
        #     taper (the slice's top is the source's top,
        #     nothing above it to overlap with). Only a lower-
        #     edge taper into the next-shadow bracket.
        #   - For the deepest bracket (index N-1): no lower-
        #     edge taper. Only an upper-edge taper into the
        #     next-peak bracket.
        #   - For middle brackets: tapers on both edges.
        #
        # The overlap width is OVERLAP_FRACTION * slice_width,
        # measured INSIDE the slice on each tapered side.
        # So the slice's actual zone-of-influence extends
        # OVERLAP_FRACTION further on each tapered side,
        # which is where adjacent brackets cross-fade.
        weights = _compute_weights(
            source_estimate=source_estimate,
            bracket=bracket,
            is_first=(bracket is brackets[0]),
            is_last=(bracket is brackets[-1]),
        )

        # Accumulate. The weighted source estimate is added
        # in normalized [0..1] source space; the conversion
        # to uint16 happens once at the end after all
        # brackets have contributed.
        value_sum += weights * source_estimate
        weight_sum += weights

    # ---- Final per-pixel normalization ----
    #
    # Divide value_sum by weight_sum to recover the weighted
    # average. Guard against pixels where no bracket
    # contributed (weight_sum == 0) - which shouldn't happen
    # given our weight design (every pixel falls into at
    # least one bracket's full-weight or tapered region),
    # but defensive against future changes that might break
    # that invariant.
    #
    # np.divide with where= leaves the output untouched
    # (zero, from the zeros_like init) at any pixel where
    # the divisor is zero, avoiding NaN propagation. Such
    # pixels show as black in the output, which is the
    # right "I don't know" signal.
    out_norm = np.zeros_like(value_sum)
    np.divide(value_sum, weight_sum, out=out_norm, where=(weight_sum > 0.0))

    # Clip-and-round to uint16. Clipping defends against
    # extreme inputs that push the weighted average slightly
    # above 1.0 due to float rounding (shouldn't happen with
    # well-formed weights but isn't free of risk).
    out_clipped = np.clip(out_norm, 0.0, 1.0)
    out_uint16 = (out_clipped * 65535.0 + 0.5).astype(np.uint16)
    return out_uint16


def _compute_weights(source_estimate, bracket, is_first, is_last):
    """
    Per-pixel weight array for one bracket's contribution to
    the merged output. Pure numpy, no Python loops.

    Args:
        source_estimate : float32 array, shape (H, W, 3),
                          values in [0.0, 1.0]. The bracket's
                          un-remapped capture, expressing its
                          best guess for each pixel's
                          source value in normalized source
                          space.
        bracket         : the BracketSpec for this bracket.
                          Used for slice_low_norm and
                          slice_high_norm.
        is_first        : bool. True for the peak bracket
                          (index 0). Disables the upper-edge
                          taper since there's nothing above
                          to overlap with.
        is_last         : bool. True for the deepest bracket.
                          Disables the lower-edge taper.

    Returns:
        float32 array, same shape as source_estimate. Values
        in [0.0, 1.0]. Higher = this bracket should dominate
        the merged result at that pixel.
    """
    low = float(bracket.slice_low_norm)
    high = float(bracket.slice_high_norm)
    slice_width = high - low

    # Overlap width on each side of the slice, in normalized
    # source space. Same width on both sides because the
    # geometric series of slices is symmetric in log-space.
    overlap = OVERLAP_FRACTION * slice_width

    # Edges of the "full weight" core region. Inside [core_low,
    # core_high] this bracket has weight 1.0; outside, weight
    # tapers down to 0 across the overlap zone or clips to 0
    # entirely past the overlap.
    #
    # Without the is_first/is_last special cases the peak
    # bracket's core_high would be inside its slice, leaving
    # the topmost source values incompletely covered. So
    # is_first removes the upper taper (core_high = high)
    # and is_last removes the lower taper (core_low = low).
    core_low = low if is_last else (low + overlap)
    core_high = high if is_first else (high - overlap)

    # Initialize weights to zero. Below we'll set them to 1
    # in the core region and to a linear taper in the
    # overlap regions.
    weights = np.zeros_like(source_estimate)

    # Core region: weight 1.0 wherever source_estimate is
    # inside [core_low, core_high].
    #
    # Deepest-bracket asymmetry: when is_last is True, core_low
    # equals slice_low (no lower taper because there's no
    # shadower bracket to fade into). But a pixel captured at
    # cap_norm=0 in the deepest bracket produces source_estimate
    # exactly equal to slice_low - and that pixel carries NO
    # information about source values below slice_low. Including
    # such pixels in core (weight 1.0) lifts every true-black
    # source pixel to slice_low_norm in the merged output. So
    # for the deepest bracket we use a strict > comparison on
    # the lower bound, leaving cap_norm=0 pixels with weight 0
    # and (via the weight_sum=0 guard in merge()) producing
    # final black output. Other brackets keep the inclusive >=
    # behavior because their lower edge IS the upper end of
    # an adjacent bracket's taper region, where information
    # is real.
    if is_last:
        in_core = (source_estimate > core_low) & (source_estimate <= core_high)
    else:
        in_core = (source_estimate >= core_low) & (source_estimate <= core_high)
    weights[in_core] = 1.0

    # Lower taper: linear ramp from 0 at (core_low - overlap)
    # to 1 at core_low. Only relevant when is_last is False -
    # otherwise core_low IS low and the slice has no
    # lower-side overlap zone.
    if not is_last:
        taper_low_start = core_low - overlap  # equivalently: low (the slice's actual bottom)
        in_lower_taper = (source_estimate >= taper_low_start) & (source_estimate < core_low)
        # Linear ramp 0..1 across the overlap. We add a
        # tiny epsilon to the denominator only conceptually;
        # numpy handles div-by-zero with infs, which would
        # propagate badly. Since overlap > 0 by construction
        # (it's OVERLAP_FRACTION * slice_width with both
        # factors positive), no guard is actually needed
        # here in code.
        weights[in_lower_taper] = (
            (source_estimate[in_lower_taper] - taper_low_start) / overlap
        )

    # Upper taper: linear ramp from 1 at core_high to 0 at
    # (core_high + overlap). Only relevant when is_first is
    # False - peak bracket extends all the way to source top.
    if not is_first:
        taper_high_end = core_high + overlap  # equivalently: high
        in_upper_taper = (source_estimate > core_high) & (source_estimate <= taper_high_end)
        weights[in_upper_taper] = (
            (taper_high_end - source_estimate[in_upper_taper]) / overlap
        )

    return weights