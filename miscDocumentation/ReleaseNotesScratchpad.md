# V0.11.0 (20260531)
## Notes: First stable in a while now!
## Added: 
### Auto Whitebalance Measure.
Now we finally have a tool in the VOP that does the white-balance more automatically (though the AWB-R and AWB-B will remain accessible in the GUI as a way to tweak outside of the "accountants truth"). How it works is simple. It first tries to find an exposure where middle grey is not in the noise floor and not having a channel clipped. Then it takes the middle section of the screen and does a measurement to see how far off from neutral middle grey it is. It applies what it thinks should be applied to the channel gains to get there. It fires off another exposure. Does a new measurement and loops through that until it reaches a satisfactorally amount of neutral grey. It then presents you with the results, the image of the latest VOP approved exposure and applies the values to the AWB-R and AWB-B in the main section.

### Other stuff
The other stuff that has been added in the previous prereleases survived so check out those release notes. 

## Changed:
 

## Fixed: 
### Incorrect fit and fill scale functions when non square PAR is used.
At some point when we added the Anamorphic functionality, the fit and fill to FOV broke when the non square PAR is used (for anamorphic results). This should now be fixed.