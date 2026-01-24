# VOP

The VOP, or Video Optical Printer. 

This is a project that aims to build a contraption called a Video Optical Printer, or VOP for short. 

In essence, it's a device that's a meld between several different older methods of image manipulation. 

1. an old school Kinescope (where a film camera was mounted in front of a TV screen in order to record the image to film) 
2. an old school animation stand. Where a film camera is mounted atop a table that holds a place to put things to be animated. 
3. the old Scanimate system. Where a video feed from one camera could be manipulated and warped in real time, rendered to a screen that's then picked up by a second camera that is then fed to some recording device or directly broadcast. 
4. Slit Scan animation systems. where art and masks would be animated during exposures independently from the movement of a motion controlled camera. Think warp drives of Star Trek: TNG, stargate sequence of 2001, and the title sequence of Superman (1978).
5. Optical Printers. Where a camera is aimed at a projector and both can be manipulated both in which frames are in their gates at any time and animated masks and overlays can be bipacked to make advanced multiple exposures. even moving the projected image on the screen. 

The aim is to create a device that can function as an animation stand, but can also be fed a video or still image to a monitor that sits at the place of the animation background. By doing this we can get a sort of virtual production setup functioning. Like the LED-walls used at ILM at their Volume setups. 

A bonus is that we can also use the setup without actually putting animation cels or cutouts in between the monitor and the camera. That way we can capture the output of the background screen over a period of time for each exposure. By doing this we can get a result that mimics old slit-scan animation without needing a complex fully reproducable frame by frame servo motor controlled motion control rig. We can achieve that because the camera doesn't have to move, neither does the monitor. Just the image on the screen has to rotate and scale in 3D space. And even a mere Raspberry Pi 5 should be able to do a single texture plane at 4K at the speed needed to fill a 60Hz monitor. 

Another bonus is that as the screen is actually a light source, it also can be used for backlit animation. 

And we can put real physical filters between the monitor and the camera at the depth we want to create interesting difractions and blur effects or whatever we want/can consceive of. 

The project consists of a few elements. 

1. The stand. 

This is the physical frame that holds everything together. I see it looking basically like a photo-booth from the outside. A sort of Arcade Cabinet that has heavy black cloth covering the opening so you can work in it while keeping stray light away. While this is written first, it'll probably be built last. 

2. The Pi

This will be a Raspberry Pi 5 that will be the brain of the contraption. It will be connected to the Pi HQ camera for full 4K 4:3 capture of exposures. And it also will be running the HDMI-monitor on its HDMI port nr 2. It's GUI will be on another monitor on HDMI port nr 1. 

3. The background-monitor. 

This is a simple computer monitor that probably will be a normal flat computer screen. Connected to the Pi with HDMI. It can be fed either with the pi providing a still image for simplest use as a background for animation on top of it, like regular peg-registered cels or cutout animation or backlit animation. Or the pi can feed it video generated on the on board GPU for slit-scan effects. Or the pi can get a video feed from my desktop to provide full power that it can provide with Blender or any other source I can come up with. At first it will be using some TFT screen I already have. but for best results, something that can provide pure blacks will be needed to keep the blacks as blacks for the cameras sensor during exposures that can go on for sometimes more than a minute. 

4. GUI monitor.
A simple monitor that shows the menu system of the VOP and provide setup for what will be shown. And this monitor should also turn dark when exposure is captured by the camera so as to not contaminate the results. 

5. The Camera

A Raspbery Pi HQ Camera using a zoom lens (or a microscope lens when that's needed). This is the singular eye of the contraption. Everything that goes on underneath it getting captured by this lens. 

6. A Web App GUI. As input of all the needed parameters for each keyframe will balloon, a better way than writing long csv files will be needed, so a web server will berunning on the Pi providing the graphical interface both for the GUI monitor in the cabinet. And for remote setup and monitoring at my desktop. 

-----------------------------

List of Dependencies

A basic instruction to how to set one of these up yourself. 

------------
Just adding a line to test out development branch and new organisation workflow on the codeberg page. 