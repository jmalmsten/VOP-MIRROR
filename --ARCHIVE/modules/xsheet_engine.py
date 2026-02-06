"""
VOP Module: xsheet_engine
Version: v0.1.0
Description: In-memory interpolation. Translates a few keyframes into a full animation
"""

import csv, os

# These headers must match your CSV column headers exactly
HEADERS = [
    'frame',
    'image',
    'color_hex',        # This is the color of the projector's light. At default, it's FFFFFF which is white light. But you can use other colors. 
    'exposure',
    'focus',
    'wb',
    
    # The frames start smear transform
    'tl_x_start', 'tl_y_start',
    'tr_x_start', 'tr_y_start',
    'br_x_start', 'br_y_start',
    'bl_x_start', 'bl_y_start',
    
    # The frames end smear transform
    'tl_x_end', 'tl_y_end',
    'tr_x_end', 'tr_y_end',
    'br_x_end', 'br_y_end',
    'bl_x_end', 'bl_y_end'
]

class XSheet:
    def __init__(self, filepath, default_duration):
        self.keyframes = {}                     # Dictionary: {frame_number: {data_row}}
        self.sorted_frames = []                 # List of frames we actually have keys for
        self.duration = default_duration

        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                # Use DictReader to access collumns by their name
                for row in csv.DictReader(f):
                    self.keyframes[int(row['frame'])] = row
            # Store keys in order so we can find 'between frames
            self.sorted_frames = sorted(self.keyframes.keys())

    def get_frame_data(self, f_num):
        """
        Calculates the state of the printer for any frame number.
        Uses Linear Interpolation (LERP) between keyframes (subject to future change)
        """

        if not self.sorted_frames: return None

        # --- SAFETY CHECK: BOUNDARY CLAMPING ---
        if f_num <= self.sorted_frames[0]:
            k1 = k2 = self.sorted_frames[0]
        elif f_num >= self.sorted_frames[-1]:
            k1 = k2 = self.sorted_frames[-1]
        else:

            # 1. Identify which two keyframes the requested frame sits between
            k1 = self.sorted_frames[0]
            k2 = self.sorted_frames[-1]
            for i in range(len(self.sorted_frames)-1):
                if self.sorted_frames[i] <= f_num <= self.sorted_frames[i+1]:
                    k1, k2 = self.sorted_frames[i], self.sorted_frames[i+1]
                    break
        
        # 2. Calculate 't' (the percentage of progress from k1 to k2)
        # t = 0 means we are at k1, t = 1.0 means we are at k2
        t = 0.0 if k1 == k2 else (f_num - k1) / (k2 - k1)

        # Start with static values (strings don't interpolate)
        data = {'frame': f_num, 'steps': self.duration,
                'image': self.keyframes[k1]['image'],
                'color_hex': self.keyframes[k1]['color_hex']} # does this mean that the hex-color doesn't change?
        
        # 3. Interpolate all numeric fields (coordinates, exposure, focus)
        for field in [h for h in HEADERS if h not in ['frame', 'image', 'color_hex']]:
            v1 = float(self.keyframes[k1][field])
            v2 = float(self.keyframes[k2][field])
            # Formula: StartValue + (Difference * Progress)
            data[field] = v1 + (v2 - v1) * t

        return data
    def get_total_frames(self):
        """
        Returns the highest frame number defined in the sheet.
        """
        return self.sorted_frames[-1] if self.sorted_frames else 0
        