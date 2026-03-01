1. Run this in terminal on desktop: 
ffplay -i tcp://0.0.0.0:5555?listen -fflags nobuffer+discardcorrupt -flags low_delay -probesize 32 -analyzeduration 0 -sync ext -vf "setpts=0, drawbox=x=iw*0.1-15:y=ih*0.1-15:w=30:h=30:c=green, drawbox=x=iw*0.9-15:y=ih*0.1-15:w=30:h=30:c=green, drawbox=x=iw*0.1-15:y=ih*0.9-15:w=30:h=30:c=green, drawbox=x=iw*0.9-15:y=ih*0.9-15:w=30:h=30:c=green"

2. Navigate the terminal to the CaliTools folder (where you found these instructions). Then run this on the Pi to get the video feed from the pi to the desktop
python3 vop_setup_align.py

3. Align the crosshairs on the HDMI screen to match with the boxes in the camera's output feed. That ensures the camera is square on the monitor. 

4. Adjust focus so you get the moire-effect from the focus target in the middle. 

If all works well, it should be aligned and in focus. 