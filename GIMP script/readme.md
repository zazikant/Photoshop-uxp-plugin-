# Only use 2.10.8 or 2.10.38 onwards version of GIMP
# C:\Users\Asus\AppData\Roaming\GIMP\2.10\plug-ins Place python script here.
  ##First open notepad -> paste python code -> save as codename.py because you can see notepad in bottom right has "UTF 8" . save that note pad to above path. later you are free to update this same py file with vs code.

whats working: 
1. Outpainting: select Q mask and invert it to select outside of image. give prompt: "outpaint this image" it will outpaint it or else *upscale to canvas width*..
2. Upscaling: select Q mask and dont invert it to select image. give prompt: "upscale  image, hi resolution" it will upscale it to canvas width..
3. Similar Style Reference Image: Same selection as above with inverting it to outside of image. give prompt: "Fill this image coherently" will make similar style image.
