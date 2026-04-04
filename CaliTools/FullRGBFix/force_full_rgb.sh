#!/bin/bash
# VOP Utility: Force HDMI-A-1 to Full RGB (0-255)
# This overrides the Limited Range (16-235) default on Pi 5
# Please see the Wiki for instructions on how to implement
# this fix.
/usr/bin/kmstest -c HDMI-A-1 -P "Broadcast RGB=1" < /dev/null
