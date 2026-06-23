# modules/notifier.py
#
# VOP event notifier — best-effort push notifications to the operator's phone
# (and any other subscribed device) via a SELF-HOSTED ntfy server on this Pi.
#
# ---------------------------------------------------------------------------
# WHY THIS EXISTS
#   An 'execute' job can run for hours, stacking exposures onto the latent
#   image while you're off doing something else. This module lets the engine
#   ping your phone when a long job finishes or dies, so the terminal doesn't
#   need babysitting. ntfy is the transport: a tiny self-hosted HTTP pub/sub
#   server (installed by deploy_vop.sh) that the phone subscribes to over the
#   LAN / VPN.
#
# ---------------------------------------------------------------------------
# DESIGN RULES (same spirit as the leds.py "cannot throw" sysfs writer)
#   * BEST-EFFORT, NEVER THROWS. A notification is a nicety, never load-bearing.
#     Every function swallows ALL exceptions and returns a bool. A dead or
#     absent ntfy server, a DNS hiccup, a timeout, a bad header — none of it may
#     ever bubble up and abort a render that's already hours deep.
#   * STDLIB ONLY. Uses urllib.request from the standard library. NO 'requests'
#     dependency: nothing to add to requirements.txt, no extra licenses, small
#     enough to bundle in the dependency installer. (Earlier notes claimed
#     'requests' was already in the stack — it isn't, hence urllib.)
#   * LOOPBACK PUBLISH. We POST to 127.0.0.1 because the ntfy server lives on
#     THIS Pi. We never need to know the Pi's own LAN IP here — the phone
#     subscribes to the LAN IP, but publish and subscribe reach the same server
#     instance and the same topic, so delivery still lands on the phone.
#
# ---------------------------------------------------------------------------
# CONFIG
#   Defaults target the local ntfy server on port 7777, topic "vop-alerts".
#   Both are overridable via environment variables WITHOUT editing code:
#       VOP_NTFY_BASE    e.g. "http://127.0.0.1:7777"
#       VOP_NTFY_TOPIC   e.g. "vop-alerts"
# ---------------------------------------------------------------------------
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
import urllib.request


# --- Configuration ---------------------------------------------------------

# Base URL of the ntfy server. Loopback by default: the server is co-located on
# this Pi (see deploy_vop.sh). Override with VOP_NTFY_BASE to point elsewhere.
NTFY_BASE = os.environ.get("VOP_NTFY_BASE", "http://127.0.0.1:7777")

# The topic = the channel name. It's literally just the last path segment of the
# publish URL. The phone subscribes to this same topic. No pre-registration.
NTFY_TOPIC = os.environ.get("VOP_NTFY_TOPIC", "vop-alerts")

# Max seconds to wait on the POST before giving up. Deliberately SHORT: if the
# notifier server is wedged, we must not stall the engine. A healthy publish on
# loopback returns in well under 10 ms, so 2 s is hugely generous.
TIMEOUT_S = 2.0

# The ONLY tasks that should ping the phone — the long, walk-away jobs. The
# engine imports this set so there is a single source of truth for "which tasks
# are worth a notification." Add task names here to extend coverage later.
NOTIFY_TASKS = {"execute", "lab_invert"}


# --- Public API ------------------------------------------------------------

def send(message, title="VOP", priority="default", tags=None):
    """
    Publish ONE notification to the ntfy topic. Best-effort; never raises.

    Args:
        message:  body text shown large on the phone (str). Full Unicode is fine
                  here — the body is sent as the raw request payload, not a
                  header.
        title:    notification title (str). KEEP THIS ASCII. ntfy carries the
                  title in an HTTP header, and non-latin-1 characters (emoji,
                  en-dashes, etc.) can make Python's http client raise. We catch
                  that anyway, but an ASCII title guarantees the title shows up.
        priority: one of "min", "low", "default", "high", "urgent". Higher =
                  louder; "urgent" can punch through the phone's Do-Not-Disturb.
        tags:     optional list of ntfy tag strings (e.g. ["white_check_mark"]).
                  Tags matching emoji shortcodes render as little icons.

    Returns:
        True  if the server accepted the publish (HTTP 2xx).
        False on ANY problem whatsoever. Never raises.
    """
    try:
        # Build the publish URL: <base>/<topic>
        url = f"{NTFY_BASE}/{NTFY_TOPIC}"

        # ntfy takes the message as the request BODY. urllib needs bytes, so
        # encode as UTF-8 (the body has no latin-1 restriction).
        data = message.encode("utf-8")

        # Metadata rides in HTTP headers — the ntfy publish convention.
        headers = {
            "Title": title,
            "Priority": priority,
        }
        if tags:
            # ntfy expects a comma-separated list in the Tags header.
            headers["Tags"] = ",".join(tags)

        # Explicit POST. (urllib infers POST when data is set, but spelling it
        # out keeps the intent obvious to the next person reading this.)
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        # Fire it. 'with' guarantees the socket is closed even on early return.
        # The short timeout is the safety valve that keeps a sick server from
        # ever blocking the engine.
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            # ntfy returns 200 on a successful publish. Accept any 2xx.
            return 200 <= resp.status < 300

    except Exception:
        # Swallow EVERYTHING by design. Network down, server absent, header
        # choke, timeout — a notification failure must never touch the render.
        # Silent on purpose; drop a print() here temporarily if you need to
        # debug why a push didn't land.
        return False


# --- Convenience wrappers ---------------------------------------------------
# These keep the call sites in engine.py short and consistent, and centralize
# the "what does a success vs. error notification look like" decision here.

def notify_job_done(message):
    """Success ping — green check icon, normal priority."""
    return send(message, title="VOP - Job Done",
                priority="default", tags=["white_check_mark"])


def notify_job_error(message):
    """Failure ping — siren icon, urgent so it cuts through Do-Not-Disturb."""
    return send(message, title="VOP - Error",
                priority="urgent", tags=["rotating_light"])