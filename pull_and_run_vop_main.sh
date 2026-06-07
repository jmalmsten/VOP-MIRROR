#!/bin/bash
# VOP Launcher Script
# This script automates a git pull from nightly and runs the vop
# Using latest code
# 
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

# 0. clear the screen
clear

# 1. Stop the current VOP if it's running.
sudo systemctl stop vop

# 2. Fetch from git to make sure the local copy knows of any changes.
git fetch --all

# 2. Pull the latest nightly commit
git pull origin main

# 3. run the VOP as a service daemon
sudo systemctl start vop

# 4. Show the logs
journalctl -u vop -f
