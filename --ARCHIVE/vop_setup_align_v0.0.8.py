admininja@pi16GB:~/vop (develop) $ python3 vop_setup_align_v0.0.7.py
pygame 2.6.1 (SDL 2.32.4, Python 3.13.5)
Hello from the pygame community. https://www.pygame.org/contribute.html
CRITICAL: rpicam-vid failed to start. Check camera connection.
admininja@pi16GB:~/vop (develop) $ rpicam-hello
[2:29:57.989264792] [32962]  INFO Camera camera_manager.cpp:340 libcamera v0.6.0+rpt20251202
[2:29:58.002198556] [32965]  INFO RPI pisp.cpp:720 libpisp version 1.3.0
[2:29:58.006305385] [32965]  INFO IPAProxy ipa_proxy.cpp:180 Using tuning file /usr/share/libcamera/ipa/rpi/pisp/imx477.json
[2:29:58.017087836] [32965]  INFO Camera camera_manager.cpp:223 Adding camera '/base/axi/pcie@1000120000/rp1/i2c@80000/imx477@1a' for pipeline handler rpi/pisp
[2:29:58.017134280] [32965]  INFO RPI pisp.cpp:1181 Registered camera /base/axi/pcie@1000120000/rp1/i2c@80000/imx477@1a to CFE device /dev/media2 and ISP device /dev/media0 using PiSP variant BCM2712_D0
Made X/EGL preview window
Made DRM preview window
Mode selection for 2028:1520:12:P
    SRGGB10_CSI2P,1332x990/0 - Score: 3456.22
    SRGGB12_CSI2P,2028x1080/0 - Score: 1083.84
    SRGGB12_CSI2P,2028x1520/0 - Score: 0
    SRGGB12_CSI2P,4056x3040/0 - Score: 887
Stream configuration adjusted
[2:29:58.140527334] [32962]  INFO Camera camera.cpp:1215 configuring streams: (0) 2028x1520-YUV420/sYCC (1) 2028x1520-BGGR_PISP_COMP1/RAW
[2:29:58.140637074] [32965]  INFO RPI pisp.cpp:1485 Sensor: /base/axi/pcie@1000120000/rp1/i2c@80000/imx477@1a - Selected sensor format: 2028x1520-SBGGR12_1X12/RAW - Selected CFE format: 2028x1520-PC1B/RAW
admininja@pi16GB:~/vop (develop) $ 