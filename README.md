# **DISCLAIMER!!!**

This whole project is vibe-coded by arguing with google Gemini and it only barely runs on my prototype setup. At this moment I cannot take any responsibility for whatever setup you have or provide real guidance if you cannot replicate my results. This is my first big project with Python and Flask. I am learning this as I am going along. 

Again. IF YOU BRICK ANYTHING USING CODE HERE I CANNOT HELP YOU!

Also. This README is long as heck but I do know I have left out some very fundamental things. Mostly because I haven't gotten around to it yet. And also, this is my first public repo. I claim ignorance if I do not know what I am not putting on here. 

Also. If you think the code is a mess. I claim ignorance. Most (if not all) of this is VibeCoded with Google Gemini. I have tried policing its output. But I... well... I just wouldn't know bad code if I saw it. 

So. Once again...

**RUN THIS CODE ON YOUR OWN HARDWARE ON YOUR OWN RISK!!!**

# VOP

## Description
The VOP is a combination of hardware and software to make a tool that mimics several real world old tools used for animation, compositing and optical printing. 

### What does it actually stand for?
VOP stands for: 

- Video - because it mainly deals with video sources instead of physical film.
- Optical - because it uses an optical path between the hdmi-monitor and the sensor. 
- Printer - because it functions somewhat like an optical printer. 

### What does it aim to do?
This tool aims to replicate a bunch of several functions that older machines used to do. 

In essence. In its simplest form. It takes an input image. Puts it in a folder called ProjMag (short for Projector Magazine). And projects it onto an HDMI screen and the camera sensor records the light coming off that HDMI screen to a frame that's saved in a folder called CamMag. This image that is saved is saved as a 16 bit linear color tiff. And if you do another exposure and target that same tiff. The VOP will merge the two using additive mix. Thus making a multiple exposure. 

The real fun however starts when we start moving the image on the screen during the exposure. That way we can make motion blur like smears of the artwork. And using multiple exposures with virtual gels and bipacks. We can make colorful smears and pseudo-3D objects. 

We can even feed it a video source using the optical printer functionality and with the bipacks we can mask out areas that we don't want to be exposed and then feed it some other artwork that's smeared and put it on the unexposed areas. 

Once one start to grasp all the things these seemingly simple tools can do, a lot of very strange outputs can be possible. 

### TECHNICAL THINGS IT DOES
The VOP is built to be operated like an optical printer. And it uses certain philosophies to get there. 

#### File type
For the VOP to work adequately, I have chosen to base it all around creation and manipulation of 16 bit linear colorspace tiff-files. This keeps things easy on the math. Adding another exposure is just adding it to the pixel values already on the files. This does mean that the resulting tiff's are skewed towards the darker end, but it retains as much as possible of the input data.

In the VOP web interface you can change the **Cam Res** and **Compression** to wrangle file size and resolution requirements of your job. 

#### LIME
The LIME system is what I call the philosophy of how the VOP should handle situations where it has captured an exposure and when it goes to write the file, it sees a file with the same name already there. 

It is a short form of

**LATENT**

**IMAGE**

**MULTIPLE**

**EXPOSURE** 

And it simply means that when an image file of the same name is already there. The VOP should add the new exposure to the existing one. We treat the image sequence in the Cam Mag as a series of Latent images. Just like how a roll of film has the images in a latent stage before it's processed. The advantage of course for this digital version is that we can peek at the latent file at any stage of the multiple exposures it's going to get without ruining the image. 

### What can't it do right now that I am working on adding?
At this moment, the VOP is a glorified Motion Blur Machine. It only let's the smear follow the same path as the main keyframes. My next big release for the VOP aims to break this out to let you move the smear independently from the main keyframe inputs. That way you can do what I'm calling "MultiDimensional Smears" or MDS. 

Another thing I am planning on doing is to have a BiPack on both the Projector and Camera Side. That way I can put in masks and have the MDS go all the way into Slit Scan results. As you can then have artwork move in one direction. A slit cut out and moving in another way and the main keyframes moving in yet another way. And the camera can have its own mask. 

And as a bonus I am also planning on making an Animation Desk Mode. Where I can manually step through the main Frames. Put things on top of the HDMI monitor. And finally Trigger the exposure manually for each frame. I am also thinking of adding functionality to use LCD shuttered animation lights to light up the elements in front of the projection monitor. 

### What does it NOT aim to do?
- If you are looking for a reliable tool to do high end realistic composites with nondestructive workflows and deep 3D implementations. Look elsewhere. This is a tool to take 2D planes. Move them in virtual 3D space and expose a latent image file. If you mess up with the VOP. You need to start over. If you want to put in an .OBJ as the projection image. You'd need to fork this project. Because it's not at all in my targets anytime soon. 
- If you are looking at this and thinking, why on earth do I not use the power of a modern GPU with Blender and do all these things all inside a desktop computer? Then all I can say is simply... if I wanted the perfect sound... I would have gotten the CD edition. I know this is a very convoluted workflow. But it is a workflow I want to explore, with all the faults and blemishes it entails. You don't get a vinyl record for the pristine sound. You get it for the very particular defects it brings to the sound.

### Who is this intended to be used by?
Mainly... me. I'm just putting this on a public repo in case someone out there stumbles upon it and wants to explore this particular workflow. Also. I am also open for suggestions on how to make this work better without sacrificing the intended workflow. 

In short. If you want to try out making video the way motion pictures used to make things before computers arrived. Then have a go with using the VOP. 

## Installation
At the moment. The installation procedure is a bit undocumented. But here's a rough outline. 

### Hardware needed:
- **Raspberry Pi 5 16GB** - probably, the VOP can be run on a lesser board. But this is what I have in my prototype.
- **Raspberry Pi Camera HQ** - This is the camera I chose for my prototype. It provides low level access to everything through the cable. And it uses C and CS mount lenses on my prototype. There's also an M12 mount version that I have not tried myself. 
- **Lens** - My prototype uses the versatile 8-50mm zoom. It's a bit finicky and not that great in terms of clarity. But until I get an OLED screen it'll do. I'll probably swap it out to a 25mm prime lens to reduce distortion and significantly bump up the clarity. 
- **SD card with Raspberry Pi OS Lite (64 bit)** - Again. Probably can be run with other OS. But I chose this because it's built for the Pi and it is built to be run headless. No desktop environment or anything taking up precious resources. 
- **HDMI Monitor** - This is what will be showing the image to the camera. My Prototype is using a simple desktop 22 inch monitor. I am looking into building the next prototype with a more fitting 13 inch OLED. Because black levels are a big factor for this whole tool. And at the moment. You can't get better black levels than OLED.
- **Tripod or gantry or something to line things up** - you'll want something steady to hold the camera, the pi and the HDMI monitor. You'll also want something that can be adjusted in all axes to line things up. 

### Getting it to the Pi
- Use whatever you feel is needed to clone the repo onto the Pi in a folder that can be easily accessed. 
- **Tip:** I do highly recommend setting up a mount point somehow so that you can reach into the mags and pull out the workprints and mag folders. 

### Dependencies
- Here's me being a bit chaotic comes in. This is all "vibe coded" and I have been installing and downloading things here and there. I do not at this moment have a full list of all the dependencies you'll need to run it. This is part of "run at your own risk" comes in. 

### Lining up tool
If you look in the CaliTools folder, I have put a simple script that helps a lot in lining up the camera to the monitor. Read the instructions in that folder to get it running. It assumes your desktop/laptop is on Linux. And if all goes well. You should get a live feed from the camera and 

## Running it

Once the hardware is connected and lined up. You should be able to use your terminal to navigate to the root VOP folder and run `python3 vop.py`. Once that is running you should see something like this in the terminal: 

```
admininja@pi16GB:~/vop (develop) $ python3 vop.py
=========================================
 VOP Server (v0.1.8) is online.
 UI available at: http://<PI_IP>:5000
=========================================
 * Serving Flask app 'vop'

 * Debug mode: off
 ```

 When you see that. You should be able to get to the web interface as it suggests, at `http://<PI_IP>:5000`

## Using it
Once you see the web interface you should be greeted with a few sections. 

- At the top, you have a full width **status** section. It shows status of the VOP engine. If it's synced using the current_job.json and if you are running a job it will provide status updates for it. What you'll also find there are an estimation of the free space and during the job you'll see how long it'll probably take to complete. And once a job is finished, you'll get a link to the latest workprint. 
- Under that you have a couple of sections. 

    - The main one on the left is the **Preview screen**. This shows preview images to help you set things up using the interface on the right and the Exposure Sheet below. 
    - On the right you have buttons and the constants of the job. 
        - **ENGINE CONTROLS** - Here you have your main buttons for running the VOP
            - **PROJ PROBE** - Short for Projector Probe - This button looks at the Target Frame and Subframe that is defined using the inputs below the buttons. Using those coordinates. It looks at the exposure sheet and determines where the projection image will be at that particular point. It renders that to a temporary image file and displays it on the preview screen on the left. 
            - **CAM VIEW** - This is like the PROJ PROBE, only it will actually do a full smear exposure to a temporary image and apply the gels and bipacs so you can see what will be exposed to that frame. 

            Using both Proj Probe and Cam View will help you setting things up for a job. 
            - **RENDER SEQUENCE** - This is the big green button. When this is pressed. The VOP will take the constants and the exposure sheet and build up how the projection image will move for each and every frame and proceed to run through the whole sequence. 
            
            REMEMBER! This whole tool is built with the assumptions of a real world camera with real world light sensitive film. If there is a latent image in the cam mag for that frame. The VOP will expose the new light on top of it. This is not a bug. This is by design. It is up to you, dear user, to pull out the latent image tiff's from the CamMag if you do not want them to be ruined. If you accidentally started a third exposure with the wrong settings and/or keyframe inputs. I am sorry, you'll have to start over again. 
            - **PANIC STOP** - Ok, so maybe you started a run with 500 frames in the exposure sheet. You realize that something was input wrong and you want to start over. This is the button to just stop whatever the VOP is doing so you can correct things without having to wait for the whole sequence to finish. 
            - **NUKE MAG** - This simply deletes whatever is in the CamMag folder. All of its content. No matter what is in there, good exposure, bad exposure. You press the button, it's gone. This will actually throw up a prompt to make sure you are certain you want to nuke it. 

            - **Target Frame** - This points the probe towards a frame in the exposure sheet. This can be used to target any frame in the sheet. Even those between the keyframes. This is so you can check what the interpolator will be doing. 
            - **Subframe** - This uses a float to pinpoint exactly where during a smear you want to be looking with the probe. 0.0 is at the start of the smear of that frame. 1.0 is at the end of the smear of the frame. This isn't actually used in CamView but it can be helpful with the Proj Probe. 
        - **HARDWARE & GLOBALS** - Here you find the technicals of the job that don't change from frame to frame.
            - **FPS** - Short for Frames per Second. As the main output is a tif image sequence, the FPS doesn't really matter in the final full res output. But for the workprint previews, this sets up what framerate should be used by ffmpeg. 
            - **GAIN** - This sets the analog and digital gain of the camera. This can be useful to boost up the exposures. But. For the most part. For smear jobs. We are dealing with rather long exposures. You'll probably have more trouble making things dark enough than making it brighter. So for most jobs. I'd recommend leaving it at 1.0 for the cleanest possible output. 
            - **AWB R** & **AWB B**- This sets up the camera's manual whitebalance. I recommend doing some experiments when you have your camera and monitor combo set up. They are float values to set up how much gain each channel should have compared with each other. R is the Red red channel and B is the blue one. Green is not adjusted. You get the whitebalance correct by nudging one or the other or both of the Red and Blue channel compared with the constant of Green. It's a bit of trial and error. I guess someone have made a tool to automate this but I have not. Once the magical numbers are found, I suggest leaving them there and noting them down somewhere for future use. 
            - **Proj FOV** - Short for Projector Field of View - As the projector is running its own little 3D engine, it needs to know the field of view of its virtual camera. At default this is set to 45 degrees. What you want is up to you. Crucially, it does not have to match the real world FOV of the sensor and lens combo of the real world camera. Get creative here. Lower numbers mean more zoomed in. Higher numbers are more zoomed out. 
            - **Cam Res** - Short for Camera Resolution - Here you set what resolution you want the camera to output. At full res you get 4056x3040. For my prototype I have this set to half both dimensions at 2028x1520. Both because I don't need the ultra high resolution for my testing and because the Zoom Lens I'm using only really is rated at 3MP anyway. Lower numbers mean lower resolution and lower filesizes. 
            - **Mono** - This is a trick to eek out better images from the VOP, when I am not actually needing full RGB camera captures. 
                - Default is **Off**. So it works like a regular RGGB bayer camera. At this default, it exposes and processes the images like you expect. 
                - When switched to **On**. The projector shows the images like usual but as the result is read from the sensor the VOP assumes the input is in greyscale. So it balances the bayer sensor color channels out and gets much cleaner monochrome output image. Then, when that conversion is done. The VOP applies the Camera Gel color to it before handing it over to the usual LIME system. 
            - **Compression** - This tells the VOP if you want to use full uncompressed tiff files for safety or if you are ok with using the losslessly compressed zip algorithm to reduce the file-size. Combining the Cam Res and the Compression, you can get the filesizes for tests down from 74MB to roughly 3-10 MB depending on the content of the image. 

        - **PROJECTION TARGET** This section tells us about what the image it's manipulating actually is.
            - **Active Image (ProjMag)** - This is a single image that can be uploaded to the VOP and it is the visible image used for the smears.
                - **EXPERIMENTAL:** if you upload a video, ffmpeg will kick in and try to convert it to an image sequence for use with the step printing functionality. This is not fully implemented yet. 
                - **DESTRUCTIVE DISCLAIMER** - There's no real way to look into the ProjMag folder and do things to the images there. So whenever a new image is uploaded to the ProjMag. Whatever is in there is nuked. This is not a bug. This is a feature. The VOP is not a place to keep things long term. 
            - **FIT FOV** - As the coordinate system in 3D can be a bit arbitrary, this button will try to help with establishing what a unit is in the 3D world. It takes the measurements of the Active Image loaded to the ProjMag comparing it to the FOV set up at Proj FOV and using some math magic it will measure how the world has to be scaled so that the image is full screen without crop using the z-position at frame 1. At default the z-position is -1. and with the fit working correctly it should scale things so that the edges that touch the frustrum (virtual cameras viewing cone) are set up to be at -1 to 1. That way, if you want to move it fully off screen at that depth you need to just move it more than 1 unit away. This is all mainly to help with setting up the VOP so you more easily can move things around.
    - **EXPOSURE SHEET** - Here's where you set up all the things that should move during the sequence. I'll take you through the inputs for a keyframe row one by one. It is modeled after exposure sheets used in 2D animation. From left to right you have values for each frame and from top to bottom you have time passing.
        - **#** - This is the keyframe number. You don't change it. It just keeps track of where you are in the exposure sheet
        - **FR** - This is the master frame we are targeting. The first one is usually 1. But the next frame is up to you and your needs for the job. It could be 2 or 58 or 200043. The interpolator will be using this number to space out how many inbetween frames it has to generate. 
        - **INT** - Interpolation mode - This selects if you want a smoothed (Smth) out curve or if it should be a linear motion (Lin). There's also ease in (In) or ease out (out). 
        - **C** - Corner - This is here to make it possible to make sharp corners with the keyframes. If you don't want a sharp corner, you want a curve. You deselect it. It's off by default. 
        - **SRC** - This is Source Anchor. If you have uploaded a video to the ProjMag so the VOP has converted it to a tiff sequence, this should select which file in the sequence you are using for this frame. And with it you can then run the step printing logic... this is not really implemented yet. 
        - **STP** - This is also a part of the step printing side. With it you set the number of frames the projector image sequence (not the VOP keyframe sequence) should be andvanced for each frame being exposed. 
        - **POS** - Here the position of the projection image is defined as X, Y, Z floats. By default it's set as "0.0,0.0,-1.0". Negative Z values are farther away from the camera. 
        - **ROT** - Here the rotation of the projection image is defined. Tilt, Yaw, Rot. They are set as floats where 1.0 is a full rotation. Default is "0.0,0.0,0.0" to have it facing the camera while directly in front of the camera. 

        --- At present there's no parenting or camera manipulation available. All movement has to be defined by the POS and ROT values.

        - **PG** - Short for Projection Gel - This emulates having a single color gel on the projector. In the VOP, this is simply a multiplication of the incoming pixel value by the color value set here. In practice, you can use this to colorize monochrome projection images on the projection side. This value is also largely negated if you run the VOP with Mono mode active (see above)
        - **CG** - Like PG above. CG is short for Camera Gel. And it emulates having a single color gel on the camera side. Like the PG, it will take the incoming pixel values and multiply them with the color value you set here. When run with Mono mode active (see above), we can force the monochrome output of the projection back into fully saturated colors.
        - **EXP** - Short for Exposure Time - This is set as float seconds. 1.0 being one full second of exposure. This is the exposure time that the VOP will use for the smear movement calculations and the practical exposure time for the camera. In practice, this value will set the subframes of the smears for your exposure. Because if you allot 1 second for exposure, the interpolator will use that time with the refresh rate of your hdmi monitor to calculate where the projection image will be for each refresh of the monitor. If you have that 1 second. And you have a refresh rate of 60Hz. That's how many subframes the smear will be built with. 60 subframes. 2 seconds gives you 120 subframes and so on.
        - **SD** - Short for Smear Distance - This sets how far the smear will be calculated. 0.0 means you get no smear. The projection image will just stay perfectly still during the exposure. 1.0 means you get a full frame worth of smear. This means the interpolator looks at the keyframes and does a smear fully between the individual frames. If we use the analogy of shutter angle. 0.0 is a shutter angle of 0 degrees. 1.0 is a shutter angle of 360 degrees. And a normal filmic motion blur of real time motion would be at 0.5 for 180 degrees. But. This value is deliberately made to be overcranked. If you put in 2.0 the smear will be calculated with the start end end being 2 frames worth of motion. I have not set a real limit here. You can have a smear length of 10 or 20 or 100 frames. And depending on the motion you have set up, it can get really strange really fast. 
        - **PH** - Short for Phase - This is where you set where you want the smear to be centered. 0.0 is the start of the smear will be the start of the exposure. 1.0 is the opposite with the smear trailing from the position. This might not sound all that useful for a single pass job. But. If you do several exposures with the same artwork and exposure sheet. You can make sure that a smearless exposure always is at the start or the end of the long smear. 
        - **X** - For all keyframes except the first one, you have a red X. It simply deletes the keyframe of that row. 
    - **+ KEY** - This button adds a keyframe to the end of the exposure sheet. 
    
    -- At the moment, there is no way to add keyframes between existing keyframes and no way to reorder the keyframes. At this moment I just haven't prioritized that niceity --
    
    - **VOP CHEAT SHEET** - This is a section that shortly explains the functions in the Exposure Sheet. Simply there to be a quick reference during setting up the Exposure Sheet. 

## Example use cases
### A white logo flying in while spinning and a blue 10 frame light streak follows it. At the end it centers on frame and the light streak shrinks into the white logo and dissapears into it. 
This is a very simplistic double exposure (maybe more if you want more elements, but lets stick to the simple white logo with blue smear part for this example)

1. Open the VOP. Make sure it's ready. Projection monitor lined up and everything. 

        Start the setup

2. Make sure nothing is in the Cam Mag. Easiest here is to hit the red **NUKE MAG** button. Since we don't want anything from a previous run. Just accept the warning prompt that comes up. 
3. Look through thte **HARDWARE & GLOBALS** to see that it's all set as we want. For a regular run like this. Let's do a standard setup. 
| input | Value |
| --------- | --------- |
| FPS | 24 |
| Gain | 1.0 |
| AWB R | 3.18 |
| AWB B | 1.45 |
| Proj FOV | 45 |
| Cam Res | 2028x1520 |
| Mono | On |
| Compression | ZIP |

    Here's a short explanation of why I chose those values. 
    
    **FPS** - 24 is the standard for motion picture film. 
    **Gain** - 1.0. For this example I don't need any added gain. I want it as clean as possible. And I don't need the values boosted. 
    **AWB R** and **AWB B** - These are values I have found to work for my prototype setup yours will vary. And you can fiddle around to get interesting color result. For my setup, this makes white go white. And grey stay reasonably neutral. (although as we are running in mono mode, these values are actually negated)
    **Proj FOV** - 45. Just a simple neutral wide. 
    **Cam Res** - 2028x1520 - For my setup and the example. Setting it to half res (actually quarter the full pixel count as halving both dimensions makes it a quarter) is fine enough. If you have a higher res projection monitor and better lens and you feel you need the full resolution. Go ahead and bump that number up.
    **Mono** - On - For my setup. There's a slight deficiancy in how the colors are shown on the monitor and then filtered on the camera's bayer sensor. By using Mono mode On. I can bypass that completely. Just feeding the monochrome image into the sensor and colorizing it with the **CG** later in the chain. 
4. Set up the **PROJECTION TARGET** - Here we set up the target to be a bitmapped high resolution logo made in Krita and saved as a black and white .png. 
    1. Press the upload button. 
    2. Navigate to the logo you want to use. 
    3. Select and press open. 
    4. There will be a warning here that says you are hereby deleting whatever is in the ProjMag folder. Confirm this. 
    5. Now you'll see the image file name in the **Active image (ProjMag)** field. 
    6. If you want to, you can normalize the **World Scale** by hitting **FIT POV**. This will ensure that at normal distance (usually x,y,-1.0) the artwork fits the screen snuggly. I find this to be a good starting point when setting things up. 
5. Go down and fill in your first Keyframe. To start with let's just see where things go. 
    - **#** - This is not touched by the user.
    - **FR** - Set it to 1 for the first frame.
    - **INT** - Set to smth for a simple ease in ease out animation
    - **C** - We want curves here so leave it unchecked
    - **SRC** - leave blank (we're not using an image sequence)
    - **STP** - See SRC
    - **POS** - Let's just leave it at "0,0,-1" for the moment. 
    - **ROT** - Let's leave it at "0.0,0.0,0.0". Just to keep it facing the camera.
    - **PG** - Leave it as white. 
    - **CG** - Leave it as white. (this is to make it easier to see during setup)
    - **EXP** - Let's do a 4 second exposure. Set it to "4.0". This gives me 240 subframes for the smear (4 seconds*60Hz refreshrate = 240 subframes)
    - **SD** - Let's set it to the 10 frames.
    - **PH** - Set it to 1.0 to have the smear follow the image. 
6. Now. With that initialization. At the start of the row you'll find a **Go** button. This sets the probe (basically the playhead) at that frame. So press it to move it to frame 1. You will see the **Target Frame** up at the right under the **PANIC STOP** and **NUKE MAG** buttons show frame 1. 
7. Up to the right. Hit **PROJ PROBE**. This will tell the VOP to look at your first keyframe. Figure out where it's at in the world space and generate the image that would be sent to the projection monitor. But it will instead put in on the preview window on the left. If all went correctly. You should see the logo fill the preview screen with grey outside the preview area. 
8. Now. Make sure the camera is connected and the lens cap is off and the HDMI monitor is running and connected to HDMI1 on the Pi. 
9. Hit **CAM VIEW**. This will tell the VOP to make a full exposure with the available keyframe data but before pushing it to the **LIME** system it does like the **PROJ PROBE** button and pushes it to the preview screen instead. You should now see that the HDMI monitor goes through a sequence. 
    1. It turns black for about half a second.
    2. The image is shown not moving for 4 seconds.
    3. The monitor goes black again for about half a second. 
    
    After it has finished processing. The resulting camera capture should show up on the web interface in the preview area. 
10. Now. Let's colorize it. Go down to the keyframes. select **CG** and select blue and confirm. 
11. Repeat the steps 7 and 9 to see that the **PROJ PROBE** shows you a white version of the image (because we use the mono mode), and when using the **CAM VIEW** image you'll see the image on the HDMI monitor is equally monochrome but the image you get in the preview is colorized to blue. 
12. Now. Move it away from the full size plane. Like 20 units. So for the position we'll make it 
    
    0.0,0.0,-20

13. Hit the **PROJ PROBE** button to quickly check where it is. It should have shrunk considerably. 
14. Let's move it away on the left. By doing the point 12 and 13 over and over I determine that I leave the screen at roughly -16 units on the x axis. So my first keyframe will be at

    -16, 0, -20

15. Now I want it to rotate during the animation. Let's keept the rotation simple. Set the rotation to 

    0, 0, -2

    This will rotate the image two full revolutions. Of course, since we have only one keyframe, if it was on screen we would see it just as not rotated. 
16. In fact. Let's add that second keyframe with the **+ KEY** button at the bottom. 
    
    By default. The VOP should just repeat the inputs from the first keyframe. If it doesn't it's a bug and I should be working on fixing it. In fact during my testing with the Main branch version. It seems it doesn't use the last keyframes by default. 
17. Fill in the values here
    - **FR** - set it to 48 so it's 2 seconds down the line in the keyframing. 
    - **INT** - Leave it at smth. We still want the ease in and out. 
    - **C** - We want to force the following frames to be still here so we'll invoke the corner value
    - **SRC** and **STP** - Leave blank. 
    - **POS** Let's put it right back in the center of the frame. 

        0,0,-1
    - **ROT** - Make the logo the right side up so we keep the suits happy. 

        0,0,0
    - **PG** - Keep white
    - **CG** - Keep blue
    - **EXP** - Stay at 4.0 for keeping the exposure stable. 
    - **SD** - 5.0 Just to start to pull the smear back in. 
    - **PH** - 1.0 to keep the smear trailing and not leading. 
19. For that second keyframe you just created. Hit the **GO** button to set the probe to the end of the current animation. And check where you're at with the **PROJ PROBE** and **CAM VIEW** buttons. You will notice that during **CAM VIEW** the logo will be spinning and flying to the point of frame 48. And the resulting preview image will show you the smear of frame 48. 
20. Let's add a third keyframe. Hit the **+ KEY** and change the following values for this new one: 
    - **FR** - set it to 96. Because we want the image to stand still for 2 seconds after the 48 frame mark. 
    - Leave the **C** to be enabled. We still want the artwork to be standing still at the center frame. 
    - Leave the **POS** and **ROT** the same as in the second keyframe. Because we don't want it to move. 
    - change the **CG** to white to make it fade into white and in turn add to the white of the second exposure we'll do later. 
    - Keep the **EXP** at 4 seconds. 
    - Change the **SD** to zero to enforce that you do not want any smear now. 
    - Keep the **PH** at 1. 

21. Again. Check where you are with the **GO** button of the keyframe and the **PROJ PROBE** and **CAM VIEW** buttons. You can even with the **Target Frame** and **Subframe** inputs look at specific frames and subframes (only applicable to **PROJ PROBE**) to understand what happens during the interpolation. 
22. Now. If you are happy with the way things go. You can take a deep breath and hit the big green **RENDER SEQUENCE** button and the VOP will run through this first exposure job. 

23. This is where you get to take a sip of coffee and contemplate what other things you want to do with the results. Because... the full 4 second animationrun we have set up will take roughly....  12-14 minutes. You can monitor the progress by looking at the status bar at the top. It will show you which frame it is working on, the estimated time left of the job. The Free drive space for the CamMag and the estimated job size and finally an progress bar visually showing the progress.

    If you want to you can also peek at the files as they are produced by navigating to the CamMag folder with your operating system. Between frame 1 and 48 they should have a clear blue tint and the animation should have a heavy smear. And from 49 to 96 they have the logo stand still should turn white until the end. And the files themselves should be around 5-10 MB each. 

    Also. I guess you have already noticed. But the terminal window you used to start up the VOP will have a running log of all the things you are doing while using the VOP. This is for debugging and just seeing what is going on moment by moment. The VOP does not "call home" in any way. I am not interested in the output that's not sent to me manually by a user. This terminal output is mainly for your benefit as the end user. 

24. When its finally done. The status bar will update and show a link **VIEW LATEST WORKPRINT**. Click it to see the animation you have just done. This is a low bitrate quick and dirty render based on what's in the CamMag. It can be used to review progress but is not intended to be used in a final project. When you are done admiring the work. You can start to work with the second exposure. 
25. Now. The second exposure will not take nearly as much setup. Because we will reuse the same artwork and everything. The only thing we want to change is the **SD** and the **CG**. That's all. We'll make the smear distance 0 so it doesn't smear at all. And the Camera Gel we set to white for all three keyframes. Go ahead and check the frames if you want with the probe and cam views. Just to see how things change. 
26. Start the second run. 

    OK. Hold up here. Remember. DO NOT use the nuke mag button here. Because that would clear out the blue smear pass we spent 23 steps creating. And we'll need those files there to put the second exposure on. WHAT YOU SHOULD DO  is to just make sure the keyframes of the second pass is correct. And press **RENDER SEQUENCE** 

    The VOP will then run the whole sequence again. Using the modified keyframes and expose those results onto the existing latent image files. 

    Remember. This whole system is built to behave like a real motion picture Optical Printer/Animation stand. If there's film in the camera mag. It will expose that film. 

    If you want to be hedonistic and break the whole philosophy of the VOP. Go ahead and copy over the latent files as they are BEFORE you hit **RENDER SEQUENCE** the second time. I cannot stop you. But I will judge you... from afar. Coward. :D

27. Go ahead and take another coffee equivalent break. This second run will take the same amount of time as the first run. And like the first run. You can peak at the files as they are saved. If all goes as planned. You can see the second exposure's crisp non-smeary version in white being burned in on the first exposure's smear.
28. When it's done. Congratulations! You have now done a two exposure animation! Have a look at the workprint. If You feel like you don't need to add anything more. You are now done. You can go to the CamMag. Copy the whole tiff image sequence to a desktop or laptop of your choice and use them in whatever way you want in whatever NLE that accepts a tiff sequence input. 
29. If you are done for the moment and don't need to use the VOP. Just go to the terminal you used to start the VOP and hit ctrl+C to halt the server and close the Python script.

# Contributing
If you feel like you can contribute to the code. Give me a message somehow. If you have specific code things that can be fixed or improved. Do the issues thing. I am trying to keep the issues updated myself, so I might find it there. 

But. I have a dayjob that is long away from coding and I am likely to label most incoming mail as spam. But I might find the contributions interesting enough to include. You are probably way... way better at coding things than my meager skills that's still heavily reliant on Google Gemini Vibe-coding. 

This project is and will for the foreseeable future be open source.



