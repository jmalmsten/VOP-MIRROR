"""
VOP X-Sheet Generator
Version: v0.0.1
Description: Compiles 16-point 4D animation sheets. 
             Auto-detects first image in 'Projector/' for the template.
"""
import csv
import os
import sys

# --- CONFIG & PATHS ---
PROJECTOR_DIR = "Projector"

def load_config_duration():
    """Reads DEFAULT_DURATION from config.txt, or defaults to 0.5."""
    if os.path.exists("config.txt"):
        with open("config.txt", "r") as f:
            for line in f:
                if "DEFAULT_DURATION" in line and "=" in line:
                    try:
                        val = float(line.split("=")[1].strip())
                        return val
                    except:
                        pass
    return 0.5

def get_first_image():
    """Scans Projector/ folder for the first available image."""
    if os.path.exists(PROJECTOR_DIR):
        files = sorted(os.listdir(PROJECTOR_DIR))
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.tiff', '.tif')):
                print(f"[AUTO] Found '{f}' in {PROJECTOR_DIR}/. Using for template.")
                return f
    print(f"[AUTO] No images found in {PROJECTOR_DIR}/. Using 'test_mask.png' as placeholder.")
    return "test_mask.png"

# --- HEADERS ---
FULL_HEADERS = [
    'frame', 'image', 'steps', 'color_hex',
    'tl_x_start', 'tl_y_start', 'tr_x_start', 'tr_y_start',
    'br_x_start', 'br_y_start', 'bl_x_start', 'bl_y_start',
    'tl_x_end', 'tl_y_end', 'tr_x_end', 'tr_y_end',
    'br_x_end', 'br_y_end', 'bl_x_end', 'bl_y_end',
    'exposure', 'focus', 'wb'
]
KEY_HEADERS = [h for h in FULL_HEADERS if h != 'steps']

def create_template(filename):
    """Creates a fresh x-sheet.csv using auto-detected image and user coordinates."""
    img = get_first_image()
    print(f"[ACTION] Creating new template: {filename}...")
    
    try:
        with open(filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=KEY_HEADERS)
            writer.writeheader()
            
            # Keyframe 1: Blue Gel with horizontal squeeze/smear
            writer.writerow({
                'frame': 1, 'image': img, 'color_hex': '#0000FF',
                'tl_x_start': 0, 'tl_y_start': 0, 'tr_x_start': 1, 'tr_y_start': 0,
                'br_x_start': 1, 'br_y_start': 1, 'bl_x_start': 0, 'bl_y_start': 1,
                'tl_x_end': 0.4, 'tl_y_end': 0, 'tr_x_end': 0.6, 'tr_y_end': 0,
                'br_x_end': 0.6, 'br_y_end': 1, 'bl_x_end': 0.4, 'bl_y_end': 1,
                'exposure': 500, 'focus': 35, 'wb': 4000
            })
            
            # Keyframe 24: Red Gel, static image (no smear)
            writer.writerow({
                'frame': 24, 'image': img, 'color_hex': '#FF0000',
                'tl_x_start': 0, 'tl_y_start': 0, 'tr_x_start': 1, 'tr_y_start': 0,
                'br_x_start': 1, 'br_y_start': 1, 'bl_x_start': 0, 'bl_y_start': 1,
                'tl_x_end': 0, 'tl_y_end': 0, 'tr_x_end': 1, 'tr_y_end': 0,
                'br_x_end': 1, 'br_y_end': 1, 'bl_x_end': 0, 'bl_y_end': 1,
                'exposure': 500, 'focus': 35, 'wb': 4000
            })
        print("[SUCCESS] Template created with your custom coordinates.")
    except Exception as e:
        print(f"[ERROR] Could not write template: {e}")

def compile_sheet(input_file, output_file):
    """Reads keyframes and interpolates into the filled sheet."""
    print(f"[ACTION] Compiling {input_file} into {output_file}...")
    duration = load_config_duration()
    keys = {}

    try:
        with open(input_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                keys[int(row['frame'])] = row
    except Exception as e:
        print(f"[ERROR] Failed to read guide file: {e}")
        return

    sorted_frames = sorted(keys.keys())
    if not sorted_frames: return

    try:
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=FULL_HEADERS)
            writer.writeheader()
            
            for f_num in range(sorted_frames[0], sorted_frames[-1] + 1):
                k1 = sorted_frames[0]; k2 = sorted_frames[-1]
                for i in range(len(sorted_frames)-1):
                    if sorted_frames[i] <= f_num <= sorted_frames[i+1]:
                        k1, k2 = sorted_frames[i], sorted_frames[i+1]; break
                
                t = 0 if k1 == k2 else (f_num - k1) / (k2 - k1)
                row_data = {
                    'frame': f_num, 'steps': duration, 
                    'image': keys[k1]['image'], 'color_hex': keys[k1]['color_hex']
                }
                
                num_fields = [h for h in FULL_HEADERS if h not in ['frame', 'steps', 'image', 'color_hex']]
                for field in num_fields:
                    v1 = float(keys[k1][field])
                    v2 = float(keys[k2][field])
                    row_data[field] = v1 + (v2 - v1) * t
                
                writer.writerow(row_data)
        print(f"[SUCCESS] Compiled {sorted_frames[-1]} frames using {duration}s duration.")
    except Exception as e:
        print(f"[ERROR] Failed to write filled sheet: {e}")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "x-sheet.csv"
    print("--- VOP X-Sheet Compiler v0.0.1 ---")
    
    if not os.path.exists(target):
        create_template(target)
    else:
        compile_sheet(target, "x-sheet_filled.csv")