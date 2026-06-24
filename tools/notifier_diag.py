
#!/usr/bin/env python3
# tools/notifier_diag.py
#
# Standalone diagnostic for the VOP error-NOTIFICATION path, in the same spirit
# as tools/brk_diag_merge.py: it reuses the REAL modules.notifier and reproduces
# engine.py's except-block logic verbatim, so you can watch a genuine exception
# route to a phone push WITHOUT editing engine.py, restarting the GPU engine
# daemon, or running an actual exposure.
#
# WHY a harness instead of breaking the engine:
#   The GPU engine is a PERSISTENT daemon (vop.py launches it once, line ~114,
#   and reuses it). It holds every imported module in memory as compiled
#   bytecode, so source edits don't apply until it's restarted, and a syntax
#   slip in the deeply-indented execute block just stops it booting. This
#   harness sidesteps all of that and tests the logic in isolation.
#
# WHAT it proves:
#   * modules/notifier.py imports cleanly
#   * NOTIFY_TASKS gating behaves (long jobs notify; interactive tasks stay quiet)
#   * a really-raised exception is formatted and sent via notify_job_error
#   * the push actually lands on your subscribed phone
#
# RUN (from the VOP repo root, exactly like the BRK harness):
#   ./venv/bin/python tools/notifier_diag.py                 # task=execute -> NOTIFIES
#   ./venv/bin/python tools/notifier_diag.py --task preview  # -> stays SILENT (correct)

import os
import sys
import argparse

# Make the real project modules importable the way the engine sees them: engine.py
# lives in modules/ and imports its siblings by bare name, so we put modules/ on
# the path and import the genuine notifier — no reimplementation.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "modules"))

import notifier  # the REAL module under test


def main():
    ap = argparse.ArgumentParser(description="Exercise the VOP error-notification path.")
    ap.add_argument("--task", default="execute",
                    help="task name to simulate (default: execute). Try 'preview' "
                         "to confirm interactive tasks stay silent.")
    args = ap.parse_args()
    task = args.task

    print(f"[notifier_diag] simulating a crash during task '{task}'")
    print(f"[notifier_diag] NOTIFY_TASKS = {sorted(notifier.NOTIFY_TASKS)}")

    # --- Below is a VERBATIM copy of engine.py's task try/except shape. --------
    # If you ever change the engine's hook, mirror it here so the harness stays
    # honest about what the real code does.
    try:
        # Force a real exception — the same KIND of unexpected runtime failure
        # the engine's except clause exists to catch.
        raise RuntimeError("synthetic failure for notifier diagnostics")
    except Exception as e:
        # vvv identical to the engine's gated error hook (Edit D) vvv
        if task in notifier.NOTIFY_TASKS:
            ok = notifier.notify_job_error(f"{task.upper()} failed: {e}")
            print(f"[notifier_diag] '{task}' is in NOTIFY_TASKS -> push sent, ok={ok}")
            print("[notifier_diag] check your phone for an URGENT 'VOP - Error' push.")
        else:
            print(f"[notifier_diag] '{task}' NOT in NOTIFY_TASKS -> stayed silent (correct).")
        # ^^^ identical to the engine's gated error hook (Edit D) ^^^


if __name__ == "__main__":
    main()
