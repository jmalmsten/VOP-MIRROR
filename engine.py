"""
VOP Module:     engine.py
Version:        v0.0.78-stable
Description:    Primary execution loop. Dependencies isolated to external modules.
                This is the conductor. It reads the JSON, sets up the window, calls the camera,
                and routes the variables to the mathematics and graphics modules.
"""
import os
import sys
import json
import time
import argparse
import pygame

# Import our custom VOP compartmentalized libraries
import interpolator
import vop_math as vmath
import camera_hardware as hw
import color_utils as cutil
import graphics_utils as gfx

# CRITICAL SYSTEM VARIABLE:
# We force the SDL library (which Pygame uses) to bypass the X11/Wayland desktop entirely.
# KMSDRM writes the graphics directly to the Linux hardware frame buffer, allowing the 
# Raspberry Pi to output pure visuals via HDMI without running a desktop environment.
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

def log_audit(msg): 
    # Prints formatted console logs for terminal tracking.
    print(f"[{time.strftime('%H:%M:%S')}] AUDIT: {msg}")

def save_frame_async(buffer_file, output_file, tiff_flag, cam_gel_rgb, frame_num, mono_forced):
    """
    Passes the heavy OpenCV lifting to the color_utils module.
    It writes to a heartbeat file upon completion so the Flask UI knows to update the progress bar.
    """
    try:
        success = cutil.process_and_stack_latent_image(buffer_file, output_file, tiff_flag, cam_gel_rgb, mono_forced)
        if success:
            with open("/tmp/vop_heartbeat", "w") as f: 
                f.write(str(frame_num))
    except Exception as e: 
        log_audit(f"Save Error: {e}")

def run_vop_engine(job_path):
    """
    The main execution wrapper triggered via the command line.
    """
    # Parse the job JSON sent by the Flask frontend.
    with open(job_path, 'r') as f: 
        job_data = json.load(f)
        
    # Map out the absolute directory paths.
    base_path = os.path.dirname(os.path.abspath(__file__))
    cam_mag_dir = os.path.join(base_path, "CamMag")
    proj_mag_dir = os.path.join(base_path, "ProjMag")
    static_dir = os.path.join(base_path, "static")

    # Pass the JSON to the interpolator to map the keyframes.
    timeline = interpolator.Timeline(job_data)

    # Boot the Pygame display system.
    pygame.init()
    screen = None
    
    # Initialization Loop: Sometimes the KMSDRM driver takes a split second to release from a previous job.
    # We attempt to bind the screen up to 5 times.
    for _ in range(5):
        try:
            # Require OPENGL and force DOUBLEBUF (back-buffering) to prevent image tearing.
            screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
            if screen: break
        except: 
            time.sleep(0.2)
            
    if not screen: 
        sys.exit(1)
        
    # VOP UI RULE: Hide the mouse so the arrow doesn't get photographed by the camera.
    pygame.mouse.set_visible(False)
    WIDTH, HEIGHT = screen.get_size()
    
    # Ask the graphics module to spin up the ModernGL context and compile the shaders.
    ctx, prog, vao = gfx.init_render_pipeline()
    
    # Initialize the Texture Cache.
    tex_mgr = gfx.TextureManager(ctx, proj_mag_dir, job_data)
    
    # Extract global variables that don't change frame-by-frame.
    world_scale = float(job_data.get('coord_scale', 1.0))
    mono_active = (job_data.get('mono_mode') == 'on') 
    
    # Push the mono boolean into the shader program immediately.
    prog['mono_mode'].value = mono_active
    res_str = job_data.get('cam_res', '2028x1520')

    def execute_exposure(frame_num, is_preview=False):
        """
        The core operation loop. Executes one physical camera exposure.
        """
        # 1. Ask the interpolator which file from the ProjMag we should be looking at.
        playhead = timeline.calculate_playhead_at(frame_num) if tex_mgr.is_sequence else 0.0
        
        # 2. Tell the graphics module to load that specific frame into VRAM.
        tex, aspect_ratio = tex_mgr.load(playhead)

        # 3. Request the spatial/temporal variables for this exact frame.
        center_st = timeline.get_state(frame_num)
        smear_len = center_st['s']      # Length of the exposure (Seconds)
        shutter_ph = center_st['ph']    # Phase offset (e.g., 0.5 centers the motion blur on the frame)
        
        # 4. Calculate the absolute time window of the exposure relative to the animation track.
        t_start = frame_num - (smear_len * shutter_ph)
        t_end = frame_num + (smear_len * (1.0 - shutter_ph))
        
        # 5. Determine the physical execution durations.
        x_ms = float(center_st['s']) * 1000.0
        
        # VOP TIMING RULE: Add 1000ms total to provide a strict 500ms black header and 500ms black tail
        # to guarantee the shutter captures the entire motion curve smoothly.
        total_ms = x_ms + 1000.0
        
        # Calculate how many sub-steps we need for motion blur (approximating 60 renders per second).
        num_steps = int(x_ms / 16.666) + 1
        path_cache = []

        # PRE-COMPUTE: We pre-calculate all matrices for the motion path *before* the camera clicks.
        # Doing this live inside the rendering loop can drop frames.
        for i in range(num_steps):
            # Map index 'i' to a time percentage 't_norm'.
            t_norm = i / max(1, num_steps - 1)
            t_frame = t_start + (t_end - t_start) * t_norm
            st = timeline.get_state(t_frame)
            
            # Fetch the completed 4x4 matrix from the vop_math module.
            mvp = vmath.get_frustum_fit_matrix(
                float(job_data['fov']), aspect_ratio, world_scale, 
                st['p'], st['r'], WIDTH, HEIGHT
            )
            
            # Save the matrix and the Projector Gel color to the path cache array.
            path_cache.append({'mvp': mvp, 'c': st['c'].astype('f4')})
        
        # 6. Define output paths
        buf_f = f"/tmp/vop_buf_{frame_num}.dng" if not is_preview else "/tmp/vop_prev_buf.dng"
        out_f = os.path.join(cam_mag_dir, f"latent_{str(frame_num).zfill(4)}.tif")
        
        # 7. Start the physical camera capture process in the background.
        cam_proc = hw.trigger_capture(buf_f, total_ms, job_data['gain'], job_data['awb_r'], job_data['awb_b'], res_str)
        
        # 8. Sleep the thread to allow the camera sensor to boot up.
        hw.wait_for_sensor_prime()

        # 9. Set the stopwatch to 0.
        anchor = time.time()
        
        # 10. THE DRAW LOOP
        while (time.time() - anchor) * 1000 < total_ms:
            elapsed = (time.time() - anchor) * 1000
            
            # Wipe the frame buffer black.
            ctx.clear(0,0,0)
            ctx.viewport = (0, 0, WIDTH, HEIGHT)
            
            # If we are within the actual exposure window (ignoring the 500ms headers/tails)
            if 500.0 <= elapsed <= (500.0 + x_ms):
                
                # Retrieve the pre-computed matrix that matches our current elapsed time.
                idx = int(((elapsed - 500.0) / x_ms) * (len(path_cache) - 1))
                idx = max(0, min(len(path_cache)-1, idx))
                step = path_cache[idx]
                
                # Inject the variables into the graphics pipeline.
                prog['filter_color'].write(step['c'])
                prog['mvp'].write(step['mvp'])
                tex.use()
                
                # Execute the draw command.
                vao.render()
                
            # Flip the back buffer to the physical projector via KMSDRM.
            pygame.display.flip()
        
        # 11. Cleanup and Processing
        ctx.finish()
        cam_proc.wait() # Ensure rpicam-still has completely closed the DNG file.
        
        # Calculate the median Camera Gel color for this frame.
        avg_cg = (timeline.get_state(t_start)['cg'] + timeline.get_state(t_end)['cg']) / 2.0

        # Dispatch the DNG file to color_utils to convert it into a final usable TIFF (or JPEG).
        if is_preview:
            cutil.generate_sensor_preview(buf_f, static_dir, avg_cg, mono_active)
        else:
            tiff_flag = 8 if job_data.get('tiff_compression') == 'zip' else 1
            save_frame_async(buf_f, out_f, tiff_flag, avg_cg, frame_num, mono_active)

    # --- EXECUTION ROUTING ---
    if job_data.get('type') == 'preview':
        # UI "Proj Probe" Route: Draws the scene internally and captures the screen buffer directly.
        frame_t = float(job_data.get('probe_frame', 1)) + float(job_data.get('probe_sub', 0))
        playhead = timeline.calculate_playhead_at(frame_t) if tex_mgr.is_sequence else 0.0
        tex, aspect_ratio = tex_mgr.load(playhead)

        st = timeline.get_state(frame_t)
        ctx.clear(0,0,0)
        ctx.viewport = (0, 0, WIDTH, HEIGHT)
        
        mvp = vmath.get_frustum_fit_matrix(
            float(job_data['fov']), aspect_ratio, world_scale, 
            st['p'], st['r'], WIDTH, HEIGHT
        )
        
        prog['filter_color'].write(st['c'].astype('f4'))
        prog['mvp'].write(mvp)
        tex.use()
        vao.render()
        
        # Extract the pixels directly from VRAM to build the UI preview JPEG.
        pixels = ctx.screen.read(components=3)
        ctx.finish()
        cutil.write_screen_capture(pixels, WIDTH, HEIGHT, static_dir)
        
    elif job_data.get('type') == 'cam_preview':
        # UI "Cam View" Route: Triggers one physical exposure and returns an 8-bit JPEG.
        execute_exposure(float(job_data.get('probe_frame', 1)), is_preview=True)
        
    else:
        # Standard Job Route
        if os.path.exists("/tmp/vop_heartbeat"): 
            os.remove("/tmp/vop_heartbeat")
            
        # Discover all explicit keyframes to define the start and end loop.
        all_frames = [k['f'] for track_keys in timeline.tracks.values() for k in track_keys]
        if not all_frames: return
        
        f_start, f_end = min(all_frames), max(all_frames)
        
        # Execute the main render loop.
        for f in range(f_start, f_end + 1):
            execute_exposure(f)
            
    # Purge VRAM and close the application safely.
    tex_mgr.release()
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    run_vop_engine(parser.parse_args().job)