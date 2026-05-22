"""
VOP Module:     brk_sequencer.py
Description:    Bracketed-exposure slice generator for BRK mode.

                Given a per-job bracket_count and bracket_stops, plus
                the hardware-calibrated t_peak, returns a list of
                BracketSpec tuples - one per capture the engine will
                make for each frame in a BRK job.

                Each bracket's slice is the portion of the source's
                16bpc range that gets mapped to screen 0..255 for
                that bracket. The peak bracket's slice covers the
                top of the source range; each shadow bracket covers
                a range bracket_stops lower (i.e. half as wide and
                shifted down by one stop's worth).

                All brackets capture at the same exposure (t_peak).
                Shadow brackets don't need longer exposures because
                their slice is remapped up to fill screen 0..255 -
                the screen does the brightness lifting that a
                longer exposure would do in a normal camera.

                The 20% overlap between adjacent slices is NOT
                applied here. This module returns the no-overlap
                "canonical" slice boundaries; brk_merger.py expands
                the boundaries internally when computing cross-fade
                weights at merge time. Keeping the overlap concern
                inside the merger means a future change to the
                overlap fraction is a one-place edit.

                Slice geometry is anchored on 65535 (the theoretical
                top of the 16bpc source range), not on a measured
                source peak. The VOP does not analyse source content;
                source-mastering is the user's responsibility.
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

from collections import namedtuple

# Each bracket the engine will capture for a single frame.
#
#   index            : int. 0 = peak bracket, 1 = first shadow,
#                      2 = second shadow, etc. Engine uses this
#                      for filename suffixing during the multi-
#                      capture sequence.
#   slice_low_norm   : float in [0.0, 1.0]. Lower bound of the
#                      source range this bracket maps to screen.
#                      Pixels below this clip to screen 0.
#   slice_high_norm  : float in [0.0, 1.0]. Upper bound of the
#                      source range this bracket maps to screen.
#                      Pixels above this clip to screen 255.
#   exposure_s       : float, seconds. Camera shutter time for
#                      this bracket. Currently always t_peak
#                      for every bracket (see module docstring).
#                      Kept as a per-bracket field so a future
#                      "longer shadow exposures" mode could
#                      coexist without changing the engine's
#                      consumption pattern.
BracketSpec = namedtuple(
    'BracketSpec',
    ['index', 'slice_low_norm', 'slice_high_norm', 'exposure_s']
)

# The minimum slice width (in normalized source space) below which
# a bracket's content becomes effectively invisible to the camera.
# Defined here so the warning helper has a single, named threshold
# to compare against rather than a magic number sprinkled in code.
#
# Rationale for 1/256:
#   - The screen is 8-bit. The smallest distinguishable code-value
#     step on the panel is 1/255 of its range.
#   - A bracket with normalised slice width below 1/256 maps a
#     source range smaller than what one panel code-value step
#     represents. So the bracket would, at best, fill the screen
#     with one or two distinct code values - useless for
#     reconstructing the source's shape across that range.
#   - 1/256 is a clean power-of-two that's slightly more
#     conservative than 1/255, leaving a touch of headroom.
EXTREME_SLICE_FLOOR = 1.0 / 256.0


def compute_brackets(bracket_count, bracket_stops, t_peak):
    """
    Return the list of BracketSpec tuples for one BRK frame.

    Args:
        bracket_count : int, 1..7. Number of bracketed captures.
                        1 = peak only (sanity-equivalent to a
                        single SSS exposure at t_peak).
        bracket_stops : float, 0.25..4.0. Photographic stops
                        between adjacent brackets. Each shadow
                        bracket is one bracket_stops further
                        down the source range than the previous.
                        1 stop = factor of 2 in source space.
        t_peak        : float, seconds. Calibrated exposure that
                        lands screen-white near sensor saturation.
                        Read from calibration.json by the engine
                        before calling this function. NOT
                        re-validated here - garbage in, garbage
                        out, by design (the engine's job is to
                        guarantee t_peak is sane before this
                        runs).

    Returns:
        list of BracketSpec, length == bracket_count, ordered
        peak-first (index 0 is the peak bracket).

    Raises:
        ValueError if bracket_count or bracket_stops are out of
        their declared ranges. We fail loud here rather than
        clamping silently - the GUI's HTML constraints
        (min/max/step on the inputs) should prevent this from
        ever happening at runtime, so an exception is a signal
        that something went around the GUI.
    """
    # Input validation. Fail loud, not silent. The GUI clamps
    # these at input time so a bad value here means someone
    # edited current_job.json by hand or the slice 12 engine
    # code mishandled the type coercion - both are bugs worth
    # surfacing immediately.
    if not (1 <= bracket_count <= 7):
        raise ValueError(
            f"brk_sequencer: bracket_count must be in 1..7, got {bracket_count}."
        )
    if not (0.25 <= bracket_stops <= 4.0):
        raise ValueError(
            f"brk_sequencer: bracket_stops must be in 0.25..4.0, got {bracket_stops}."
        )

    # Slice geometry.
    #
    # The peak bracket's slice covers the top of the source range
    # down to (1 / 2^bracket_stops). For bracket_stops=1.0 that's
    # [0.5, 1.0] in normalized space, equivalent to source values
    # [32768, 65535]. Each shadow bracket halves (or rather,
    # divides by 2^bracket_stops) both its upper and lower
    # bounds, sliding the slice one bracket_stops further down.
    #
    # Geometric series: for bracket index k (0-indexed),
    #   high_k = 1.0 / 2^(k * bracket_stops)
    #   low_k  = 1.0 / 2^((k + 1) * bracket_stops)
    # The peak bracket has k=0, so high_0 = 1.0 (screen white
    # maps to source top) and low_0 = 1.0 / 2^bracket_stops.
    #
    # Why peak-first ordering: matches the "anchor at peak,
    # bracket down into shadows" mental model the user is
    # working in. Engine iterates this list directly to drive
    # the per-frame capture sequence; reversal is a one-line
    # change at the engine layer if a use case for it appears.
    brackets = []
    for k in range(bracket_count):
        # Use float division explicitly. Python 3 already does
        # this with `/`, but the explicit conversion documents
        # the intent and protects against future maintainers
        # accidentally introducing integer types.
        scale = 2.0 ** (k * float(bracket_stops))
        slice_high = 1.0 / scale
        slice_low = 1.0 / (scale * (2.0 ** float(bracket_stops)))

        # Clamp lower bound to >= 0. For extreme combinations
        # (high k, high bracket_stops) slice_low can become a
        # vanishingly small float; the math doesn't strictly
        # need clamping because subsequent code is robust to
        # tiny positive values, but clamping at this layer makes
        # the data hand-off to the merger cleaner. The merger
        # is allowed to assume slice_low >= 0.0 and never has
        # to defend against subnormals or negatives.
        slice_low = max(0.0, slice_low)

        brackets.append(BracketSpec(
            index=k,
            slice_low_norm=slice_low,
            slice_high_norm=slice_high,
            exposure_s=t_peak,  # See module docstring: same exposure for all brackets.
        ))

    return brackets


def warn_if_extreme(brackets, log_fn=None):
    """
    Inspect a list of BracketSpecs and emit a warning if the
    deepest bracket's slice is below the EXTREME_SLICE_FLOOR.

    This is a pure diagnostic - the brackets list is returned
    unchanged. The engine calls this once per BRK job (not per
    frame) so the warning appears at job-start audit-log time,
    not buried in per-frame chatter.

    Args:
        brackets : list of BracketSpec, as returned by
                   compute_brackets().
        log_fn   : optional callable that accepts a single string
                   argument. The engine passes its log_audit
                   function here; tests can pass a list-appender
                   or None. If None, the function is silent
                   except for its return value.

    Returns:
        bool. True if a warning was issued (deepest slice was
        below EXTREME_SLICE_FLOOR), False otherwise. Lets the
        caller decide whether to surface the warning in the
        GUI's status panel in addition to the audit log.
    """
    if not brackets:
        # No brackets at all is a strange state (bracket_count
        # 0 would have raised in compute_brackets) but defensive
        # against future callers building this list by hand.
        return False

    deepest = brackets[-1]
    width = deepest.slice_high_norm - deepest.slice_low_norm

    if width < EXTREME_SLICE_FLOOR:
        msg = (
            f"BRK WARNING: deepest bracket (index {deepest.index}) "
            f"has slice width {width:.6f} of source range, below "
            f"the visibility floor of {EXTREME_SLICE_FLOOR:.6f}. "
            f"This bracket will likely produce a near-uniform "
            f"black or banded capture. Consider reducing "
            f"bracket_count or bracket_stops."
        )
        if log_fn is not None:
            log_fn(msg)
        return True

    return False