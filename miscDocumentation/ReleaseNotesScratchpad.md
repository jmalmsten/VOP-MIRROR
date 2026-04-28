# V0.7.0 (YYYYMMDD)
## Added:
### GATE, CAM and STP to the exposure sheets. 
These fields only become visible when the input of either ProjectionMag (PM) or Bipack (BP) is a video. When feeding any of them a still image, these fields are not needed and are therefore hidden to avoid cluttering things. 
#### Clarification of use:
- **GATE** - Gate specifies which frame of the video should be seen at the keyframe. This is an anchor that the interpolated frames use to calculate their own visible frames. If left empty. The interpolator simply carries on as if no new anchor has been set. If a frame number is present there, the interpolator will jump to that new anchor. No smoothed out interpolation between the anchors will be done. The progression between keyframes are entirely dictated by the CAM:STP formula. 
- **CAM** & **STP** - These show the interpolator how to find out which frame to show where. It's interpreted as **CAM**:**STP**. 1:1 means that for each 1 frame in the CamMag. The gate of the video should be advanced 1 frame. **CAM** is an integer that has to be 1 or more. 0 and negative numbers cannot be used here. **STP** can be positive and negative numbers. Positive means advancing. Negative means reversing.

    Examples:

        - 2:-3 means that for every second camera frame, the video frame should reverse 3 frames. The resulting sequence would then be (from anchor frame of 9): 9,9,6,6,3,3,0,0. 
        - 1:0 means that for every camera frame. The video should advance 0 frames. This in effect renders a paused video. 
        - 4:1 means that for every fourth camera frame. the video should advance 0 frames. Making slowed down motion. The resulting sequence would be (from anchor frame 9): 9,9,9,9,10,10,10,10,11,11,11,11

    So far. No auto-looping commands. But they are coming later.
### Added ability to click the measured black level to auto-copy the numbers to the Noise-crusher text input
This is mostly to avoid situations where I miss part of the float in my manual copy-pasting. 

## Changed:
- Added PM to the headers of the exposure sheet to clarify which columns are responsible for the Projection Mag.
## Fixes: 
## Removed:
