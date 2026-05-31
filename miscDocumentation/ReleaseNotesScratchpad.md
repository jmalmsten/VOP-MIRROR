# V0.11.0 (20260531)
## Notes: First stable in a while now!
## Added: 
### 
### Auto Whitebalance Measure.
Now we finally have a tool in the VOP that does the white-balance more automatically (though the AWB-R and AWB-B will remain accessible in the GUI as a way to tweak outside of the "accountants truth"). How it works is simple. It first tries to find an exposure where middle grey is not in the noise floor and not having a channel clipped. Then it takes the middle section of the screen and does a measurement to see how far off from neutral middle grey it is. It applies what it thinks should be applied to the channel gains to get there. It fires off another exposure. Does a new measurement and loops through that until it reaches a satisfactorally amount of neutral grey. It then presents you with the results, the image of the latest VOP approved exposure and applies the values to the AWB-R and AWB-B in the main section.

### Other stuff
The other stuff that has been added in the previous prereleases survived so check out those release notes. Wait. I never did releases for them. Well. here they are: 

#### V0.9.0 & V0.10.0 - HDR
This update introduces the third mode alongside the SSS and MDS. The new one is HDR. It is here to be used with images and video footage exposures that don't need smears but do need higher degree of tonal detail. The SSS and MDS are limited to 8bpc and this HDR mode tries to extend this to the cameras full 12bpc range by not moving the image, instead, it animates the brightness values of the pixels so that over time, darker pixels go black and lighter pixels stay on to burn in more tonal detail. Until the end of the exposure sweep where the whole image goes dark. 

#### Calibration Page
Added a second page that can be used for the calibration tools. For now, we only have added some initial measurement tools for the bracket mode.

## Changed:


### Sheet survivability
During debugging while adding bracket mode, it became apparent that we don't have to throw out the exposure sheet when switching modes. 

### Made it clearer what's what in preview
Until now, the preview was a bit ambiguous about where the image starts and ends when doing probes. This is made more clear now.

## Fixed: 
### Incorrect fit and fill scale functions when non square PAR is used.
At some point when we added the Anamorphic functionality, the fit and fill to FOV broke when the non square PAR is used (for anamorphic results). This should now be fixed.