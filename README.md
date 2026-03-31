# **DISCLAIMER!!!**

This whole project is vibe-coded by arguing with google Gemini and it only barely runs on my prototype setup. At this moment I cannot take any responsibility for whatever setup you have or provide real guidance if you cannot replicate my results. This is my first big project with Python and Flask. I am learning this as I am going along. 

Again. IF YOU BRICK ANYTHING USING CODE HERE I CANNOT HELP YOU!

Also. This README is long as heck but I do know I have left out some very fundamental things. Mostly because I haven't gotten around to it yet. And also, this is my first public repo. I claim ignorance if I do not know what I am not putting on here. 

Also. If you think the code is a mess. I claim ignorance. Most (if not all) of this is VibeCoded with Google Gemini. I have tried policing its output. But I... well... I just wouldn't know bad code if I saw it. 

So. Once again...

**RUN THIS CODE ON YOUR OWN HARDWARE ON YOUR OWN RISK!!!**

![VOP Logo with a colorful streak](readme_graphics/vop-smear-logo-001.jpg)

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

In essence. In its simplest form. It takes an input image. Puts it in a folder called ProjMag (short for Projector Magazine). And "projects" it onto an HDMI screen and the camera sensor records the light coming off that HDMI screen to a frame that's saved in a folder called CamMag. This image that is saved, is saved as a 16 bit linear color tiff. And if you do another exposure and target that same tiff. The VOP will merge the two using additive mix. Thus making a multiple exposure. 

The real fun however starts when we start moving the image on the screen during the exposure. That way we can make motion blur like smears of the artwork. And using multiple exposures with virtual gels and bipacks. We can make colorful smears and pseudo-3D objects. 

We (soon) can even feed it a video source using the optical printer functionality and with the bipacks we can mask out areas that we don't want to be exposed and then feed it some other artwork that's smeared and put it on the unexposed areas. 

Once one start to grasp all the things these seemingly simple tools can do, a lot of very strange outputs can be possible. 

### TECHNICAL THINGS IT DOES
The VOP is built to be operated like an optical printer. And it uses certain philosophies to get there. 

#### File type
For the VOP to work adequately, I have chosen to base it all around creation and manipulation of 16 bit linear colorspace tiff-files. This keeps things easy on the math. Adding another exposure is just adding it to the pixel values already on the files. This does mean that the resulting tiff's are skewed towards the darker end, but it retains as much as possible of the input data.

In the VOP web interface you can change the **Cam Res** and **Compression** to wrangle file size and resolution requirements of your job. Full Res and no compression gives you the biggest files. 

#### LIME
The LIME system is what I call the philosophy of how the VOP should handle situations where it has captured an exposure and when it goes to write the file in the CamMag, it sees a file with the same name already there. 

LIME is a short form of

**LATENT**

**IMAGE**

**MULTIPLE**

**EXPOSURE** 

And it simply means that when an image file of the same name is already there. The VOP should add the new exposure to the existing one. We treat the image sequence in the Cam Mag as a series of Latent images. Just like how a roll of film has the images in a latent stage before it's processed. The **advantage** of course for this digital version is that we can peek at the latent file at any stage of the multiple exposures it's going to get without ruining the image. 

The **"disadvantage"** is that once the new exposure is added to the latent image. You can't undo. You can only start over... from scratch. That is a feature. It will not be considered a bug.

### What can't it do right now that I am working on adding?
* At the moment of this writing it only has ProjMag and BiPack. That's it as far as sources go. I am planning on making a CamBiPack to assist with making holdout mattes.

* I am also planning on revisiting functionality to take an input video and make a sequence of still images that's loaded in the ProjMag and BiPacks. This will enable simple step-printing with the exposure sheet setting how many frames should be advanced or regressed per new frame in the camera.

* And as a bonus I am also planning on making an Animation Desk Mode (ADM). Where I can manually step through the main Frames. Put things on top of the HDMI monitor. And finally Trigger the exposure manually for each frame. I am also thinking of adding functionality to use LCD shuttered animation lights to light up the elements in front of the projection monitor. 

* What I also am thinking of doing is making some sort of API or something available that let's the end user pipe in a video feed of their choosing from an external source. This can then be paired with the ADM to have physical artwork in front of a virtual volume stage. And the VOP can tell the external source when to advance or regress. But... this is a pipe-dream thing. I am not expecting to reach that stage any time soon. 

### What does it NOT aim to do?
* If you are looking for a reliable tool to do high end realistic composites with nondestructive workflows and deep 3D implementations. Look elsewhere. This is a tool to take 2D planes. Move them in virtual 3D space and expose a latent image file. If you mess up with the VOP. You need to start over. If you want to put in an .OBJ as the projection image. You'd need to fork this project. Because it's not at all in my targets anytime soon. 

* If you are looking at this and thinking, why on earth do I not use the power of a modern GPU with Blender and do all these things all inside a desktop computer? Then all I can say is simply... if I wanted the perfect sound... I would have gotten the CD. I know this is a very convoluted workflow. But it is a workflow I want to explore, with all the faults and blemishes it entails. You don't get a vinyl record for the pristine sound. You get it for the very particular defects it brings to the sound.

### Who is this intended to be used by?
Mainly... me. I'm just putting this on a public repo in case someone out there stumbles upon it and wants to explore this particular workflow. Also. I am also open for suggestions on how to make this work better without sacrificing the intended workflow. 

In short. If you want to try out making video the way motion pictures used to make things before computers arrived. Then have a go with using the VOP. 

## Installation
At the moment. The installation procedure is a bit undocumented. But here's a rough outline of things I use to make it work. 

### Hardware needed:
- **Raspberry Pi 5 16GB** - probably, the VOP can be run on a lesser board. But this is what I have in my prototype.
- **Raspberry Pi Camera HQ** - This is the camera I chose for my prototype. It provides low level access to everything through the cable. And it uses C and CS mount lenses on my prototype. There's also an M12 mount version that I have not tried myself. But I think the sensor and all electronics would be the same.
- **Lens** - My prototype uses the versatile 8-50mm zoom. It's a bit finicky and not that great in terms of clarity. But until I get an OLED screen it'll do. I'll probably swap it out to a 25mm prime lens to reduce distortion and significantly bump up the clarity. 
- **SD card with Raspberry Pi OS Lite (64 bit)** - Again. Probably can be run with other OS. But I chose this because it's built for the Pi and it is built to be run headless. No desktop environment or anything taking up precious resources. 
- **HDMI Monitor** - This is what will be showing the image to the camera. My Prototype is using a simple desktop 22 inch monitor. I am looking into building the next prototype with a more fitting 13-14 inch UHD OLED. Because black levels are a big factor for this whole tool. And at the moment. You can't get better black levels than OLED.
- **Tripod or gantry or something to line things up** - you'll want something steady to hold the camera, the pi and the HDMI monitor. You'll also want something that can be adjusted in all axes to line things up. 
### Getting it to the Pi
- Use whatever you feel is needed to clone the repo onto the Pi in a folder that can be easily accessed. 
- **Tip:** I do highly recommend setting up a mount point somehow so that you can reach into the mags and pull out the workprints and mag folders. Because at the moment, the web interface has no export tools.
### Dependencies
- Here's me being a bit chaotic comes in. This is all "vibe coded" and I have been installing and downloading things here and there. I do not at this moment have a full list of all the dependencies you'll need to run it. This is part of "run at your own risk" comes in. 
### Lining up tool
If you look in the CaliTools folder, I have put a simple script that helps a lot in lining up the camera to the monitor. Read the instructions in that folder to get it running. It assumes your desktop/laptop is on Linux. And if all goes well. You should get a live feed from the camera and 
## Running it
Once the hardware is connected and lined up. You should be able to use your terminal to navigate to the root VOP folder and run `python3 vop.py`. Once that is running you should see something like this in the terminal: 

```
=========================================
 VOP Server is online.
=========================================
 * Serving Flask app 'vop'
 * Debug mode: off
 ```

 When you see that. You should be able to get to the web interface as it suggests, at `http://<PI_IP>:5000`

# Instructions for use
Please see the wiki for detailed instructions of how to do each thing.

# Contributing
If you feel like you can contribute to the code. Give me a message somehow. If you have specific code things that can be fixed or improved. Do the issues thing. I am trying to keep the issues updated myself, so I might find it there. 

But. I have a dayjob that is long away from coding and I am likely to label most incoming mail as spam. But I might find the contributions interesting enough to include. You are probably way... way better at coding things than my meager skills that's still heavily reliant on Google Gemini Vibe-coding. 

This project is and will for the foreseeable future be open source.