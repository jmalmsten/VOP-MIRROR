# V0.7.0 (YYYYMMDD)
## Added:
## Changed:
## Fixes: 
## Removed:

# V0.6.4 (YYYYMMDD)
## Notes:
While not much is added in features. A massive rebuild has taken place to make the VOP run well on a Pi4B with 4GB RAM
## Added:
## Changed: 
- Moved the prototype to Pi4B with 4GB for making sure it runs on lower hardware than the biggest 16 GB Pi5
- Moved the idle screen to use OpenGL to simplify rendering systems and avoid the single CPU spiking that was discovered with moving to Pi4 platform.
- Moved things around so the list of files only is sorted once at the start of the job instead of for each frame.
### Core Engine & Hardware Synchronization

- Resolved Hardware Shutter Desync: Replaced the --immediate flag in rpicam-still with a calculated --timeout (-t) delay matching PRIME_WAIT_MS (1500ms). This synchronizes the IMX477 physical shutter opening with the Python OpenGL render loop.

- Normalized Shutter Calculations: Standardized the total_ms variable as a 1:1 map for the physical shutter duration (shutter_us). Removed legacy 1000ms subtractions and additions from the camera_hardware.py and engine.py modules.

- Fixed Animation Temporal Jumps: Implemented VRAM Pre-Caching within execute_exposure. By loading textures into GPU memory before triggering the camera, we eliminated the 2–4 second thread-stall caused by synchronous SD card I/O on the first frame.

### Rendering & Optical Shutter Integrity

- Enforced Optical Shutter Blackouts: Addressed a KMSDRM/GLES driver optimization quirk where ctx.clear() was ignored if no geometry was present. The system now renders a Physical Black Quad (geometry-based clear) to ensure the monitor physically drops to 0,0,0 RGB during pre-roll and post-roll periods.

- Verified Light-Shutter Architecture: Confirmed that the 500ms pre/post-roll sequence correctly encapsulates the smear animation, protecting the sensor from rolling shutter artifacts and ensuring a clean start/stop in total darkness.
## Fixes:
- Various fixes and improvements. 
## Removed: