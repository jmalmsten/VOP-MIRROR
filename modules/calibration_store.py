"""
VOP Module:     calibration_store.py
Description:    Read/write helpers for static/calibration.json - the
                persistent store of hardware-calibration values.

                Currently holds:
                  - t_peak                  : exposure time (seconds) at
                                              which the projection
                                              monitor's max white lands
                                              near sensor saturation.
                                              Set by the ACB (Auto
                                              Calibrate for Brackets)
                                              routine on the Calibration
                                              page.
                  - black_floor_at_t_peak   : sensor brightness reading
                                              (float 0.0-1.0) of a dark
                                              target captured at t_peak.
                                              Optional; only present if
                                              the user enabled the
                                              "Include black level
                                              measurement" checkbox
                                              during ACB.

                Schema will grow over time (full LUT, white balance,
                etc.). All callers should treat missing keys as
                "not yet calibrated" and not crash.

                ===  IPC / engine-busy convention (read this first if  ===
                ===  you are editing calibration code in the future)   ===
                The engine daemon's busy state is signalled by the
                existence of /tmp/vop_cmd.json (COMMAND_FILE in vop.py).
                When vop.py dispatches a task it writes that file;
                the engine deletes it on completion. vop.py's /status
                route reports "rendering" while the file exists, "idle"
                otherwise. The frontend polls /status and gates UI on
                that signal - both job execution and calibration
                routines share this single busy-flag, so calibration
                buttons must be disabled while a job is rendering and
                vice versa. There is no separate "is calibration vs
                is job?" distinction at the IPC level.
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

import os
import json

# The calibration store lives in static/ rather than the project root
# because (a) the frontend can fetch it directly via /static/... and
# (b) it groups naturally with other engine-produced UI data like
# noise_data.json and hot_pixels.json.
CALIBRATION_FILENAME = "calibration.json"


def _store_path(static_dir):
    """
    Resolve the full path to the calibration JSON. Centralised so we
    only have one place to change if we ever move it.
    """
    return os.path.join(static_dir, CALIBRATION_FILENAME)


def load(static_dir):
    """
    Load the calibration store. Returns a dict. Missing file or
    unparseable JSON both return an empty dict - callers should
    treat missing keys as "not yet calibrated" rather than as
    errors. This lets a fresh VOP install boot cleanly with no
    calibration file at all.

    Args:
        static_dir : str, absolute path to the VOP static directory.
                     Passed in rather than resolved here so this
                     module stays free of any "where is the project
                     root?" assumption - callers know.

    Returns:
        dict. Empty {} if file is missing or unreadable.
    """
    path = _store_path(static_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        # Defensive: if somehow the file holds a non-dict (e.g. an old
        # schema or a hand-edit gone wrong), don't return it - the
        # rest of the codebase assumes dict semantics.
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, IOError, OSError):
        # Silent fallthrough to empty dict is the right behaviour here.
        # A corrupt calibration file shouldn't take down the engine;
        # the user just needs to re-run the relevant calibration to
        # rewrite the file. Audit log entries about the write itself
        # (in the engine tasks) will tell the user when calibrations
        # successfully landed; a missing/corrupt file shows up in the
        # UI as "no calibration yet" which is the same UX as a fresh
        # install.
        return {}


def save(static_dir, updates):
    """
    Merge the supplied updates into the existing calibration store
    and persist. Existing keys not mentioned in `updates` are
    preserved - so writing just t_peak does not clobber a previously
    measured black floor, and vice versa.

    Args:
        static_dir : str, absolute path to the VOP static directory.
        updates    : dict of key->value pairs to merge in. Values
                     should be JSON-serialisable scalars
                     (floats / ints / strings / bools); no nested
                     numpy arrays etc.

    Returns:
        dict. The full post-merge contents, in case the caller wants
        to log it or hand it to the frontend without a re-read.

    Raises:
        OSError / IOError if the file can't be written. We deliberately
        do not swallow write errors - if the disk is full or the static
        dir is read-only, the user needs to know rather than silently
        losing the calibration result.
    """
    current = load(static_dir)
    current.update(updates)
    path = _store_path(static_dir)
    # Pretty-print with indent=2 because this file is meant to be
    # human-inspectable (and occasionally hand-edited during dev,
    # though the GUI's manual-override path is the supported way).
    with open(path, 'w') as f:
        json.dump(current, f, indent=2)
    return current


def get(static_dir, key, default=None):
    """
    Convenience accessor for a single calibration value. Returns the
    default if the key is absent. The future BRK engine code will
    use this to fetch t_peak each frame; centralising the
    missing-key-handling lets that engine code stay readable.

    Args:
        static_dir : str, absolute path to the VOP static directory.
        key        : str. Calibration key to read.
        default    : any. Value to return if the key is missing.
                     Default None.

    Returns:
        The value at `key` if present, else `default`.
    """
    return load(static_dir).get(key, default)