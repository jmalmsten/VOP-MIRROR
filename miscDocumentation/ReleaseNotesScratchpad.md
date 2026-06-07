# V0.13.1 (YYYYMMDD)
## Added: 
### Restored the IP output for the idle screen
This one has been missed for a while. The idle screen used to show the IP and Port for the WebGUI. Now it's back.

### Rearranged the placement of the mags in the GUI
To make the sidebar on the main page less greedy in vertical space. I moved the sections for the mags up abobe the preview. As a bonus, this also sets things up for the big wood grain makeover I have planned where I make the whole VOP look and feel more like an Optical Printer visually. 

### Frame counters for all the mags.
Added a neat little frame counter so that both when probing and when executing a job. I can see which frame is loaded at which gate. Mostly as a fun visual touch, but also as a way to decode if the step-printing is out of wack.  

It's formatted like: ``####/####`` where ``####/`` is the current frame in the gate and ``/####`` is the total number of frames in the gate.

The number is four digits. 0001-9999 because, right now, the step printer logic is limited to 9999 frames. in 24 fps playback speed, that's 6 minutes, 56 seconds and 15 frames. Should be enough for most shots. Please let me know if this is too limiting. But remember that upping thte limit to 5 digits means ten times the storage space requirements... per mag. and ten times the job length in time. 

#### Stages for frame counters:
The step printers have three stages depending on what is loaded. 

- ``----/----`` - means the mag is empty and nothing is loaded
- ``SINGLE_FR`` - means that a lone image is loaded and is treated as a still image. No step printing available.
- ``0001-9999/0001-9999`` - this means a video has been ingested and transcoded to a tiff sequence that can be used with step printing.

### Font choice
To make the counters stand out and look plain cool I decided to use a segmented display font found here:
https://github.com/keshikan/DSEG

Read more about the font here:
https://www.keshikan.net/fonts-e.html

I claim no ownership of the font. I just find it neat. :)

### RENDER WORKPRINT button
Button to manually trigger creation of a new workprint even when a new full job isn't run.


## Camera Feed for Focus and alignment
Issue #198 - Added a way to get a camera feed into the GUI in order to make it easier to both line up the camera, monitor and set focus.. Find it in the calibration page. And when using it. You should see a focus chart on the screen with some crosshairs in the corners and boxes in the corners of the camera feed. You should be able to use these to line up the camera to the monitor and set focus and zoom. 

A focus peaking mode is coming once this is nailed down.

## Wood grain makeover
Mostly a GUI niceity. I want to see the VOP using a wood style. 

## Changed:
### Rearranged the sections of the GUI
In order to limit the vertical space used by the sidebar I moved the mags up as a horizontal line of sections. This is also in anticipation of the big wood-grain redesign that's coming later on.

### Moved Noise Crusher and Hot Pixel Mapper to the Calibration Page
Simply because those are calibration steps. 

### Renamed mode names
Mostly to clean it up and make them less width hungry.

### Display branding when job is nuked
When the NUKE JOB button is pressed and confirmed. The job is nuked and now a placeholder image is put into the preview. That placeholder is the branding image that's also used for the screensaver on the monitor.

### Moved copyright text to bottom

### Removed the Cheat Sheet from the bottom of the GUI
the cheatsheet.html remains for a while until I decide this change didn't become more troublesome than I wanted.

## Fixed: 
- #187 - corrected exposure time for noise measure and hot pixel mapping.
- #186 - unified naming so type is now task in the python code and json. 
- #142 - nothing left here to fix. so closed it.
- Cleaned up a little inline css codes. 
- #140 - not actionable here either. 
- #141 - the whole standalone idle_screen.py is no more already. Nothing to do here.
- When frame counter was added. It's using amber color. This is the same color that the NUKE JOB button used, so I restyled that button to match the other NUKE buttons. Just to keep the color coding consistent.
