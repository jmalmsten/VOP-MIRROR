import cv2
import numpy as np

# Create transparent 1280x720 image (4 channels: BGRA)
img = np.zeros((720, 1280, 4), dtype=np.uint8)
# Draw Red X (Blue=0, Green=0, Red=255, Alpha=255)
cv2.line(img, (0, 0), (1280, 720), (0, 0, 255, 255), 5)
cv2.line(img, (1280, 0), (0, 720), (0, 0, 255, 255), 5)
cv2.imwrite("overlay.png", img)