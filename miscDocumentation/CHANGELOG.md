# VOP Release Tracking

## v0.6.3 - (YYYMMDD)
- Added Noise floor measurement
- Added Noise Crush input
- Modified version numbering in the GUI title so it only tracks v#.# instead of v#.#.# . I'll still update the third digit in the header of the GUI though. 
- Added update to the preview to show what pixels are measured with the noise measurement function.
- Added Hot Pixel Fixer that measures hot pixels and replaces those pixels in post. 
- Added Export and Import buttons to enable saving and loading jobs. And during import, it will check to see if the version number matches the currently installed version.
- Added LAB/INVERT button that inverts the frames that are in CamMag. This enables easier holdout matte workflows within the VOP. 

## v0.6.2 - (20260406)

### Added
- Added run_vop.sh to simplify starting the vop
- Added the DVD-screensaver for when the VOP is idle
- Added drop-zones to file uploads to circumvent any browser-related hangs when a folder disappears."

## V0.6.1 - (20260404)

### Added
- Created 'Documentation' directory for project tracking.
- Added tutorials to the wiki both for first installation of VOP and fullRGB fix.

### Changed
- Moved the force_full_rgb.sh script to CaliTools/FullRGBFix/ to clean up the root
- Added ffmpeg_metadata.txt to .gitignore to clean out unnecessary file.

### Fixed
