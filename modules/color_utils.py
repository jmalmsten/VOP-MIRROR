"""
VOP Module:     color_utils.py
Description:    16-bit linear workspace modifications and latent image accumulation.
"""

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
import cv2
import rawpy
import numpy as np
import json

def apply_pedestal(img_16bit, clip_val):
    """
    Subtracts the noise floor pedestal in a float 32 workspace to prevent underflow,
    then clips at zero and returns to uint16.
    """

    if clip_val <= 0.0:
        return img_16bit
    
    int_threshold = int(clip_val * 65535)
    img_f = img_16bit.astype(np.float32)
    img_f = np.clip(img_f - int_threshold, 0, 65535)
    return img_f.astype(np.uint16)

def unsqueeze_preview_jpg(img, par_x, par_y, preview_unsqueeze):
    """
    Apply the anamorphic preview unsqueeze to a JPG-bound image.

    Used by the post-processing step of any preview pipeline that needs
    to honor the user's Preview Unsqueeze toggle. Identical math to the
    inline blocks in generate_sensor_preview, generate_comp_preview, and
    vop.py's /cam_probe route - this function exists so a third copy
    isn't added to engine.py for Proj Probe.

    Behavior:
      - If preview_unsqueeze is False, returns img unchanged.
      - If PAR is effectively 1:1 (within 1e-6), returns img unchanged.
      - If PAR > 1.0 (wide pixels), stretches X horizontally by PAR.
      - If PAR < 1.0 (tall pixels), stretches Y vertically by 1/PAR.
      - On any unexpected error, returns img unchanged with a warning
        printed - matches the defensive fallback in the inline copies.

    Why no in-place mutation: cv2.resize allocates a new array anyway,
    and returning a value is friendlier to the call sites that may
    chain post-processing steps.
    """
    if not preview_unsqueeze:
        return img
    try:
        # Defensive coercion: identical to what the inline copies do,
        # so behavior remains 1:1 if/when those callers are migrated.
        px = float(par_x) if float(par_x) > 0 else 1.0
        py = float(par_y) if float(par_y) > 0 else 1.0
        par = px / py
        if abs(par - 1.0) <= 1e-6:
            return img  # square pixels - nothing to do
        h, w = img.shape[:2]
        if par > 1.0:
            # Wide-pixel case: stretch X horizontally.
            new_w = int(round(w * par))
            return cv2.resize(img, (new_w, h), interpolation=cv2.INTER_CUBIC)
        else:
            # Tall-pixel case: stretch Y vertically.
            new_h = int(round(h / par))
            return cv2.resize(img, (w, new_h), interpolation=cv2.INTER_CUBIC)
    except Exception as e:
        print(f"[VOP WARNING] unsqueeze_preview_jpg failed (falling back to squeezed): {e}")
        return img

def letterbox_into(img, target_w, target_h, fill_bgr=(26, 26, 26)):
    """
    Scale `img` proportionally to fit inside a `target_w` x `target_h`
    canvas, then center it on that canvas with letterbox/pillarbox bars.
    Never crops; always preserves the entire source image.

    Used by Proj Probe to reframe the HDMI screen-grab so its outer shape
    matches what the camera-side previews produce - giving the user a
    consistent preview window shape across all four probe/preview buttons.

    `fill_bgr` defaults to (26, 26, 26) which matches --bg-panel from
    style.css and the no-latent placeholder background. Pure black risks
    visually merging with dark images; near-black gives a faint frame
    edge so the preview boundary is always discernible.

    Returns a uint8 BGR image of exactly (target_h, target_w, 3).
    """
    src_h, src_w = img.shape[:2]
    if src_w <= 0 or src_h <= 0 or target_w <= 0 or target_h <= 0:
        # Defensive: malformed inputs return the source unchanged rather
        # than producing a zero-size canvas downstream.
        return img

    # Aspect-fit: pick the scale that fits both dimensions inside target.
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))

    # INTER_AREA gives sharper downscales; INTER_CUBIC is the right choice
    # for upscale. Pick based on whether we're shrinking or growing.
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    scaled = cv2.resize(img, (new_w, new_h), interpolation=interp)

    # Build the canvas. np.full with a 3-tuple fill replicates the BGR
    # color across all pixels in one allocation.
    canvas = np.full((target_h, target_w, 3), 0, dtype=np.uint8)
    canvas[:, :] = fill_bgr  # broadcast fill across H,W

    # Center the scaled image on the canvas. Integer division is fine
    # here - any 1-pixel asymmetry from rounding is invisible in practice.
    off_y = (target_h - new_h) // 2
    off_x = (target_w - new_w) // 2
    canvas[off_y:off_y + new_h, off_x:off_x + new_w] = scaled

    return canvas

def generate_sensor_preview(buffer_file, static_dir, cam_gel_rgb, mono_forced, black_clip=0.0,
                            par_x=1.0, par_y=1.0, preview_unsqueeze=False):
    if not os.path.exists(buffer_file): return False

    try:
        with rawpy.imread(buffer_file) as raw:
            rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
        
        # --- Patch defective pixels immediately ---
        rgb = apply_hot_pixel_patch(rgb, static_dir)
        
        # 1. Apply the Pedestal subtraction
        rgb = apply_pedestal(rgb, black_clip)

        # 2. Convert from RGB to BGR for OpenCV
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        # Downscale to 8-bit for the preview JPEG AFTER the high-precision math
        img = (img / 256.0).astype(np.uint8)
        
        # Mono stripping logic here for previews
        if mono_forced:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
        img = (img.astype(np.float32) * gel_bgr).clip(0, 255).astype(np.uint8)

        # ANAMORPHIC PREVIEW UNSQUEEZE
        # Cam View has captured the squeezed HDMI screen. If the user has asked
        # for a preview that matches what their NLE would produce, we apply the
        # inverse of the squeeze here as a JPG-level resample. PAR > 1 means the
        # original logical X was compressed into a smaller pixel-X span, so we
        # stretch X back out by PAR. PAR < 1 means we stretch Y back out by 1/PAR.
        # The latent TIFFs on disk are NOT processed here - they stay squeezed
        # so the NLE can do the real PAR-driven unsqueeze in post production.
        if preview_unsqueeze:
            try:
                px = float(par_x) if float(par_x) > 0 else 1.0
                py = float(par_y) if float(par_y) > 0 else 1.0
                par = px / py
                if abs(par - 1.0) > 1e-6:
                    h, w = img.shape[:2]
                    if par > 1.0:
                        # Wide-pixel case: stretch X horizontally
                        new_w = int(round(w * par))
                        img = cv2.resize(img, (new_w, h), interpolation=cv2.INTER_CUBIC)
                    else:
                        # Tall-pixel case: stretch Y vertically
                        new_h = int(round(h / par))
                        img = cv2.resize(img, (w, new_h), interpolation=cv2.INTER_CUBIC)
            except Exception as e:
                print(f"[VOP WARNING] Preview unsqueeze failed (falling back to squeezed): {e}")

        cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img)
    
    except Exception as e:
        print(f"[VOP WARNING] Processing Error: {e}")

    finally:
        # Added finally block so cleanup happens even if something crashes
        if os.path.exists(buffer_file): os.remove(buffer_file)
        dummy = buffer_file.replace(".dng", ".jpg")
        if os.path.exists(dummy): os.remove(dummy)
        
    return True

def generate_comp_preview(buffer_file, static_dir, cam_mag_dir, frame_num,
                          cam_gel_rgb, mono_forced, black_clip=0.0,
                          par_x=1.0, par_y=1.0, preview_unsqueeze=False):
    """
    COMP PREVIEW (issue #175)
    Hybrid of generate_sensor_preview and process_and_stack_latent_image:
    process the freshly captured DNG identically to a real exposure (16-bit
    workspace, hot pixels, pedestal, mono, CG gel) AND additively composite
    against any existing latent TIFF for this frame, THEN downscale to 8-bit
    and write the preview JPG.

    This produces a viewfinder image showing what the exposure would look
    like if the user committed it via Execute Sequence - useful for lining
    up multi-pass shots (ProjMag, BiPack, CamMag positions) before exposing.

    CRITICAL: The existing latent TIFF in cam_mag_dir is read but NEVER
    written back. Calling Comp Preview must be safe to spam without altering
    a single bit of the actual latent on disk.

    Why the math is done in 16-bit before downscaling to 8-bit JPG:
    a real exposure's stack happens in 16-bit; downscaling first and then
    adding would crush highlights and misrepresent clipping. We mirror the
    exact path of process_and_stack_latent_image up through the cv2.add(),
    then diverge into the JPG-write path of generate_sensor_preview.
    """
    if not os.path.exists(buffer_file): return False

    try:
        # --- Demosaic the raw DNG into 16-bit linear RGB ---
        # Same call as both sibling functions, so the preview math sees the
        # same raw data the real exposure would.
        with rawpy.imread(buffer_file) as raw:
            rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)

        # --- Patch defective pixels immediately (16-bit) ---
        rgb = apply_hot_pixel_patch(rgb, static_dir)

        # --- Pedestal subtraction (Noise Crusher) in 16-bit ---
        rgb = apply_pedestal(rgb, black_clip)

        # --- RGB -> BGR for OpenCV ---
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        # --- Mono Mode handled in 8-or-16 bit safe range ---
        if mono_forced:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        # --- CG (Cam Gel) tint, applied in 16-bit float, clipped to uint16 ---
        # Note: this branch matches process_and_stack_latent_image's clip
        # range (0..65535) so the additive math below operates in the same
        # 16-bit integer space as a real execute would.
        gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
        img = (img.astype(np.float32) * gel_bgr).clip(0, 65535).astype(np.uint16)

        # --- THE ACTUAL COMPOSITE (in-memory, in 16-bit) ---
        # Look up the existing latent TIFF for THIS frame using the exact
        # path format execute_exposure writes. If it exists, additively
        # composite (saturated cv2.add) just like a real exposure run does.
        # If it does not exist, the preview just shows the new exposure
        # alone, identical to Cam Preview.
        # We DO NOT write img back to existing_latent_file. Ever.
        existing_latent_file = os.path.join(
            cam_mag_dir, f"latent_{str(int(frame_num)).zfill(4)}.tif"
        )
        if os.path.exists(existing_latent_file):
            existing = cv2.imread(existing_latent_file, cv2.IMREAD_UNCHANGED)
            if existing is not None:
                # cv2.add saturates at the dtype max (65535 for uint16),
                # which is the same behavior a real execute uses.
                img = cv2.add(img, existing.astype(np.uint16))

        # --- Now downscale to 8-bit for the JPG preview window ---
        # From here onward this matches generate_sensor_preview's tail.
        img = (img / 256.0).astype(np.uint8)

        # --- Optional anamorphic preview unsqueeze (JPG-level only) ---
        # Same logic as generate_sensor_preview - so the Comp Preview JPG
        # respects the same Preview Unsqueeze toggle that Cam Preview does.
        if preview_unsqueeze:
            try:
                px = float(par_x) if float(par_x) > 0 else 1.0
                py = float(par_y) if float(par_y) > 0 else 1.0
                par = px / py
                if abs(par - 1.0) > 1e-6:
                    h, w = img.shape[:2]
                    if par > 1.0:
                        new_w = int(round(w * par))
                        img = cv2.resize(img, (new_w, h), interpolation=cv2.INTER_CUBIC)
                    else:
                        new_h = int(round(h / par))
                        img = cv2.resize(img, (w, new_h), interpolation=cv2.INTER_CUBIC)
            except Exception as e:
                print(f"[VOP WARNING] Comp preview unsqueeze failed (falling back to squeezed): {e}")

        # --- Write to the SAME static JPG that Cam Preview uses ---
        # The front end reloads /static/probe_live.jpg for both preview
        # types, so we deliberately overwrite the same file.
        cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img)

    except Exception as e:
        print(f"[VOP WARNING] Comp Preview Processing Error: {e}")

    finally:
        # Clean up the DNG buffer just like the sibling functions do,
        # so /tmp does not slowly fill with comp_preview leftovers.
        if os.path.exists(buffer_file): os.remove(buffer_file)
        dummy = buffer_file.replace(".dng", ".jpg")
        if os.path.exists(dummy): os.remove(dummy)

    return True

def process_and_stack_latent_image(buffer_file, static_dir, output_file, tiff_flag, cam_gel_rgb, mono_forced, black_clip=0.0):
    if not os.path.exists(buffer_file): return False

    try:
        with rawpy.imread(buffer_file) as raw:
            rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
        
        # --- Patch defective pixels immediately ---
        rgb = apply_hot_pixel_patch(rgb, static_dir)
    
        # 1. Apply the pedestal subtraction
        rgb = apply_pedestal(rgb, black_clip)

        # 2. Convert from RGB to BGR for OpenCV
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        
        if mono_forced:
            # Exploit monochrome clarity by stripping color before tinting
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        
        # Now apply the CG tint (cam_gel_rgb)
        gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
        img = (img.astype(np.float32) * gel_bgr).clip(0, 65535).astype(np.uint16)

        # Check to see if file already exists
        if os.path.exists(output_file):
            existing = cv2.imread(output_file, cv2.IMREAD_UNCHANGED)
            if existing is not None:
                img = cv2.add(img, existing.astype(np.uint16))

        cv2.imwrite(output_file, img, [cv2.IMWRITE_TIFF_COMPRESSION, tiff_flag])

    except Exception as e:
        print(f"[VOP WARNING] Processing Error: {e}")

    finally:
        if os.path.exists(buffer_file): os.remove(buffer_file)
        dummy = buffer_file.replace(".dng", ".jpg")
        if os.path.exists(dummy): os.remove(dummy)
    return True

def write_screen_capture(pixels, width, height, static_dir):
    # CRITICAL FIX: Process the raw RGBA (4-channel) byte buffer from ModernGL.
    img = np.frombuffer(pixels, dtype=np.uint8).reshape((height, width, 4))
    img = np.flipud(img)
    # Convert RGBA directly down to standard BGR for JPEG saving.
    img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img)

def measure_noise_floor(buffer_file, static_dir):
    """
    Analyzes a dark frame to determine the sensor's noise ceiling at the 
    current exposure settings, draws a bounding box for UI feedback,
    and exports the result to a static JSON for the frontend.
    
    Uses the 99.9th percentile of the center crop rather than the mean — 
    the noise crusher is a threshold, so the value we want is the *ceiling* 
    the noise reaches, not its average. Setting the crusher to the mean would
    let roughly half the noise distribution survive crushing.
    
    Hot pixels are patched before measurement so they don't dominate the 
    percentile statistic.
    """
    
    if not os.path.exists(buffer_file):
        return 0.0
    
    try:
        with rawpy.imread(buffer_file) as raw:
            # Strictly linear 16-bit extraction
            rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
        
        # Patch hot pixels first so they don't contaminate the measurement
        rgb = apply_hot_pixel_patch(rgb, static_dir)
        
        # Center crop 200x200
        h, w, _ = rgb.shape
        cy, cx = h // 2, w // 2
        crop = rgb[cy-100:cy+100, cx-100:cx+100]
        
        # 99.9th percentile: the value that 99.9% of pixels fall below.
        # This is the noise's effective ceiling — set the crusher just above 
        # this and all noise gets zeroed without sacrificing legitimate signal.
        # We use 99.9 rather than 100 (max) so that a single random outlier 
        # pixel can't skew the result; 99.9% of 200x200 = ~40,000 of 40,000 
        # pixels must agree.
        ceiling_16bit = np.percentile(crop, 99.9)
        noise_float = float(ceiling_16bit / 65535.0)
        
        # --- PREVIEW GENERATION ---
        img_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        img_8bit = (img_bgr / 256.0).astype(np.uint8)
        
        # Burn a bright green rectangle to show the user exactly what area was measured
        cv2.rectangle(img_8bit, (cx-100, cy-100), (cx+100, cy+100), (0, 255, 0), 2)
        cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img_8bit)
        
        # Export the numerical result to a dedicated static JSON file
        out_json = os.path.join(static_dir, "noise_data.json")
        with open(out_json, "w") as f:
            json.dump({"measured_noise": noise_float}, f)
        
        return noise_float
    
    except Exception as e:
        print(f"[VOP WARNING] Noise Measurement Error: {e}")
        return 0.0
    finally:
        # Cleanup routine to prevent tmp folder bloat
        if os.path.exists(buffer_file): os.remove(buffer_file)
        dummy = buffer_file.replace(".dng", ".jpg")
        if os.path.exists(dummy): os.remove(dummy)

def measure_centre_brightness(buffer_file, static_dir, patch_fraction=0.05,
                              return_dict=False):
    """
    Centre-weighted brightness measurement for calibration routines.

    Reads the DNG captured by the camera, demosaics it via rawpy, takes
    a small square region at the geometric centre of the frame, and
    computes brightness metrics on it. Also writes a JPG preview of
    the full capture (with a green rectangle showing the measurement
    region) to probe_live.jpg so the Calibration page can display what
    was actually measured.

    Args:
        buffer_file    : str. Path to the DNG file just written by
                         hw.trigger_capture(). Same convention as
                         measure_noise_floor.
        static_dir     : str. Path to the static/ directory. Used for
                         the probe_live.jpg write and (via
                         apply_hot_pixel_patch) the hot pixel JSON
                         path.
        patch_fraction : float in (0, 1]. Side length of the centre
                         square as a fraction of the smaller image
                         dimension. Default 0.05 = a 5%-side square,
                         which is small enough to avoid corner
                         vignetting and large enough to average out
                         per-pixel noise.
        return_dict    : bool. When False (default), returns the mean
                         brightness as a float. When True, returns a
                         dict with mean, per_channel_max, and
                         channel_maxes - the per-channel info ACB
                         needs to detect single-channel saturation.

                         The dict form is opt-in rather than the
                         default because most callers (the manual
                         "Single Measurement" button, a future
                         exposure-preview helper, anything else that
                         just wants "how bright was this?") only need
                         the scalar. ACB is the unusual caller that
                         needs to reason about channels separately.

    Returns:
        If return_dict is False:
            float in [0.0, 1.0] - the mean brightness across R, G, B.
        If return_dict is True:
            dict with keys:
                'mean'             : float, mean across R, G, B in [0,1]
                'per_channel_max'  : float, max(R_max, G_max, B_max) in
                                     [0,1]. THIS is the metric ACB
                                     should chase - it goes to 1.0 the
                                     moment any single channel clips.
                'channel_maxes'    : tuple of (r_max, g_max, b_max),
                                     each in [0,1]. Diagnostic; ACB
                                     logs these so the user can see
                                     which channel hit the ceiling
                                     first (= WB diagnosis hint).

    Notes for future-me:
        Earlier versions of this function used cv2.imread on the DNG,
        which returns raw Bayer pattern data (not demosaiced RGB).
        That caused readings to come back at roughly 1/4 of the actual
        sensor response because three out of every four positions in
        each "channel" are zeros from the other Bayer colours. The
        correct path - matching measure_noise_floor - is rawpy with
        gamma=(1,1), no_auto_bright=True, output_bps=16, which gives
        properly demosaiced linear 16-bit RGB.
    """
    # Defensive fallback values. We construct them once here so that
    # any of the early-return paths below can hand back consistent
    # shapes. Sentinel value is 1.0 ("near saturation, back off")
    # because that's the safer direction for ACB to misread - a false
    # "low" reading would push the convergence loop toward even longer
    # exposures and waste time chasing a doomed capture.
    fallback_scalar = 1.0
    fallback_dict = {
        'mean': 1.0,
        'per_channel_max': 1.0,
        'channel_maxes': (1.0, 1.0, 1.0),
    }

    if not os.path.exists(buffer_file):
        return fallback_dict if return_dict else fallback_scalar

    try:
        # Strictly linear 16-bit extraction. Identical posture to
        # measure_noise_floor: gamma=(1,1) means no tonemap,
        # no_auto_bright disables rawpy's automatic exposure
        # correction (we want raw measurements, not "what looks
        # nice"), output_bps=16 preserves full sensor precision.
        with rawpy.imread(buffer_file) as raw:
            rgb = raw.postprocess(gamma=(1, 1), no_auto_bright=True,
                                  output_bps=16)

        # Patch hot pixels before measurement so a single stuck pixel
        # in the metering region doesn't drag any metric upward and
        # confuse ACB's "are we near saturation?" decision.
        rgb = apply_hot_pixel_patch(rgb, static_dir)

        # rawpy returns shape (H, W, 3) in RGB order. The centre
        # patch is sized as a fraction of min(H, W) so it stays
        # square on any aspect ratio.
        h, w = rgb.shape[:2]
        side = int(min(h, w) * patch_fraction)
        side = max(1, side)
        cy, cx = h // 2, w // 2
        half = side // 2

        patch = rgb[cy - half : cy + half, cx - half : cx + half]

        # Mean across all pixels and all channels - the "typical
        # brightness" metric for the manual readout.
        mean_brightness = float(patch.mean()) / 65535.0

        # 99th percentile per channel rather than raw max.
        #
        # Raw .max() is one hot pixel away from being wrong: a single
        # sensor pixel stuck at 65535 inside the metering patch makes
        # every measurement return per_channel_max=1.0 regardless of
        # actual screen brightness. ACB can't converge against a
        # constant signal - it bisects forever and the algorithm has
        # no way to recover.
        #
        # 99th percentile rejects the top 1% of pixels per channel,
        # which is roughly 56 pixels on a 75x75 patch (the size we
        # get from patch_fraction=0.05 on a 2028x1520 capture). That
        # is more than enough to mask out unmapped hot pixels while
        # still firing immediately when real clipping happens, since
        # real clipping affects thousands of pixels at once - the
        # 99th percentile saturates almost as fast as the absolute
        # max when the screen genuinely whites out.
        #
        # Compare measure_noise_floor which uses 99.9th percentile
        # for similar reasons; ACB uses the slightly tighter 99th
        # because the noise crusher wants to be conservative about
        # what counts as "noise" (more outliers ignored = lower
        # crush level = more cleanup) while ACB wants to be liberal
        # about what counts as "clipping" (fewer outliers ignored =
        # detect real saturation sooner).
        r_max = float(np.percentile(patch[:, :, 0], 99)) / 65535.0
        g_max = float(np.percentile(patch[:, :, 1], 99)) / 65535.0
        b_max = float(np.percentile(patch[:, :, 2], 99)) / 65535.0
        per_channel_max = max(r_max, g_max, b_max)

        # --- PREVIEW GENERATION ---
        # Convert to 8-bit BGR for the JPG write. Same shape /
        # bit-depth conversion measure_noise_floor uses.
        img_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        img_8bit = (img_bgr / 256.0).astype(np.uint8)

        # Burn a bright green rectangle around the measured region.
        # This matches the noise-crusher preview style and gives the
        # user visual confirmation of where the measurement happened.
        cv2.rectangle(img_8bit, (cx - half, cy - half),
                      (cx + half, cy + half), (0, 255, 0), 2)
        cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img_8bit)

        if return_dict:
            return {
                'mean': mean_brightness,
                'per_channel_max': per_channel_max,
                'channel_maxes': (r_max, g_max, b_max),
            }
        return mean_brightness

    except Exception as e:
        print(f"[VOP WARNING] Peak Measurement Error: {e}")
        return fallback_dict if return_dict else fallback_scalar
    finally:
        # Cleanup, same as measure_noise_floor.
        if os.path.exists(buffer_file):
            os.remove(buffer_file)
        dummy = buffer_file.replace(".dng", ".jpg")
        if os.path.exists(dummy):
            os.remove(dummy)
def apply_hot_pixel_patch(img_16bit, static_dir):
    """
    Reads the hot pixel map and replaces defective pixels with the median of their neighbors.
    Uses cv2.medianBlur and numpy indexing for near-instant C++ execution speed.
    """

    hp_file = os.path.join(static_dir, "hot_pixels.json")
    if not os.path.exists(hp_file):
        return img_16bit
    
    try:
        with open(hp_file, 'r') as f:
            data = json.load(f)
        
        if "pixels" not in data or not data["pixels"]:
            return img_16bit
        
        # Extract coordinates
        pts = np.array(data["pixels"])
        y_coords = pts[:, 0]
        x_coords = pts[:, 1]

        # Apply a 3x3 median blur to a copy of the image.
        blurred = cv2.medianBlur(img_16bit, 3)

        # Overwrite ONLY the defective pixels on the original image with the blurred pixels
        img_16bit[y_coords, x_coords] = blurred[y_coords, x_coords]

        return img_16bit
    except Exception as e:
        print(f"[VOP WARNING] Hot Pixel Patch Error: {e}")
        return img_16bit

def map_hot_pixels(buffer_file, static_dir):
    """
    Scans a dark frame for anomalies and saves coordinates to JSON.
    If it detects too many hot pixels ( > 0.5% of sensor), it assumes the lens cap is off.
    """
    if not os.path.exists(buffer_file): return -1

    try:
        with rawpy.imread(buffer_file) as raw:
            rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
        
        # Convert to grayscale to measure pure intensity
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

        # Calculate the mathematical noise floor and standard deviation
        mean_val, std_val = cv2.meanStdDev(gray)
        mean_val, std_val = mean_val[0][0], std_val[0][0]

        # A hot pixel is anything 10 standard deviations above the noise floor
        # We also set a hard minimum (1000) so a perfectly clean, pitch black frame doesn't trigger false positives
        threshold = max(mean_val + (10 * std_val), 1000)

        # Find coordinates where intensity exceeds threshold
        y_coords, x_coords = np.where(gray > threshold)
        hp_count = len(y_coords)
        out_json = os.path.join(static_dir, "hot_pixels.json")

        if hp_count > 15000:
            with open(out_json, "w") as f:
                json.dump({"error": "LENS CAP OFF?", "pixels": []}, f)
            return  -1

        # Convert to a standard Python list of [y, x] pairs for JSON serialization
        pixels_list = [[int(y), int(x)] for y, x in zip(y_coords, x_coords)]

        with open(out_json, "w") as f:
            json.dump({"error": None, "pixels": pixels_list}, f)
        
        return hp_count
    except Exception as e:
        print(f"[VOP WARNING] Mapping Error: {e}")
        return -1
    finally:
        if os.path.exists(buffer_file): os.remove(buffer_file)
        dummy = buffer_file.replace(".dng", ".jpg")
        if os.path.exists(dummy): os.remove(dummy)

