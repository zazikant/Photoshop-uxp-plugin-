# Only use 2.10.8 or 2.10.38 onwards version of GIMP
# C:\Users\Asus\AppData\Roaming\GIMP\2.10\plug-ins Place python script here.
  ##First open notepad -> paste python code -> save as codename.py because you can see notepad in bottom right has "UTF 8" . save that note pad to above path. later you are free to update this same py file with vs code.

# *Very Important* Rule: ONLY USE PNG FILES TO WORK WITH AND NOT JPEG. ALSO, ADD A "BOX BLUR" TO IMAGE TO GET CANNY LIKE UPSCALE OR INPAINT

whats working: 
1. Outpainting: select Q mask and invert it to select outside of image. give prompt: "outpaint this image" it will outpaint it or else *upscale to canvas width*..

2. Upscaling (place subject image in a white canvas that is 3 x bigger): select Q mask and dont invert it to select image. give prompt: "upscale  image, hi resolution" it will upscale it to canvas width.. very important: press ctrl + shift + z on gemini edit layer. it will expan the generated image to highest of resolution


3. Inpaint + Upscaler (place subject image in a white canvas that is 3 x bigger): same as point 2 upscaling.. without inverting selection, just write your prompt without keywords like Upscale " futuristic city, cars " it will select subject and blend to this theme.  press Ctrl + shift+ z to get this beautiful inpainted auto Upscaled photo


4. Similar Style Reference Image: Same selection as above with inverting it to outside of image. give prompt: "Fill this image coherently" will make similar style image.


Shortcut:

1. To view full scale of  gemini output image: click shift + s it will preview image. Then press ctrl + c and ctrl + shift + v to paste full scale output to a new window.  
