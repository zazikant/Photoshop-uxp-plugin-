# GIMP AI scripts (while using Kie script have aspect ratio configured to 1:1, 2:3, 3:2, 16:9, 9:16,  auto works.. in case you want to edit image by selecting all.. you need to mandatory choose as "auto" in pop up)

## kie.ai Grok Imagine plugins — GIMP 3.2 (current)

Two GIMP 3 plug-ins using kie.ai's **Grok Imagine Image 2.0**:

| File | Menu entry | What it does |
|------|------------|--------------|
| `kie_text_to_image.py` | Filters > AI Tools > Generate New Image with kie.ai (Grok)... | Text-to-image. The result opens in a **new image window**. |
| `kie_image_edit.py` | Filters > AI Tools > Edit Selection with kie.ai (Grok)... | Sends your current **selection** + prompt; the result is inserted as a **new layer**. |

### Install (GIMP 3.2)

1. Open (create if missing) GIMP's user plug-ins folder:

   ```
   C:\Users\Asus\AppData\Roaming\GIMP\3.2\plug-ins
   ```

2. **Create 2 folders** inside it, one per plug-in. The folder name MUST match the `.py` file name exactly (case included) — GIMP ignores the plug-in otherwise:

   ```
   C:\Users\Asus\AppData\Roaming\GIMP\3.2\plug-ins\
     kie_text_to_image\
       kie_text_to_image.py
     kie_image_edit\
       kie_image_edit.py
   ```

3. FULLY quit GIMP (check Task Manager for `gimp*.exe` processes) and start it again. Both entries appear under **Filters > AI Tools**.

### API key

1. Create a key at <https://kie.ai/api-key> — never share or commit it.
2. On first run, paste the key into the **API key** field of the plug-in dialog. It is saved locally to `C:\Users\Asus\.kie_api_key`, so you only enter it once.
3. Alternatives: set the environment variable `KIE_API_KEY` (then restart GIMP), or write the key to `C:\Users\Asus\.kie_api_key` yourself.

Requires GIMP 3.0+ (tested on GIMP 3.2.6). Uses only the Python standard library — no pip packages. Aspect ratios: `1:1, 16:9, 9:16, 4:3, 3:4` — **Edit Selection** defaults to `auto`, which sends the ratio closest to your selection so the result lines up without extra pixels. A generation typically takes 10-90 seconds.

### Troubleshooting

- **Plug-in missing from the menu** — the folder name doesn't match the file name (case included), or GIMP wasn't fully restarted.
- **"No API key"** — paste the key in the dialog, set `KIE_API_KEY`, or write it to `C:\Users\Asus\.kie_api_key`.
- **Anything fails** — every step (and full tracebacks on errors) is logged to `C:\Users\Asus\.gimp_kie_debug.log`; check the newest lines.

---

## Old Gemini / Qwen scripts — GIMP 2.10

# Only use 2.10.8 or 2.10.38 onwards version of GIMP
# C:\Users\Asus\AppData\Roaming\GIMP\2.10\plug-ins Place python script here.
  ##First open notepad -> paste python code -> save as codename.py because you can see notepad in bottom right has "UTF 8" . save that note pad to above path. later you are free to update this same py file with vs code.

# *Very Important* Rule: ONLY USE PNG FILES TO WORK WITH AND NOT JPEG. ALSO, ADD A "BOX BLUR" TO IMAGE TO GET CANNY LIKE UPSCALE OR INPAINT

whats working: 

When you want to place something with 2 images and a text prompt. In qwen or google nano banana, use this: " FOLLOW THE PROMPT" it will do as mentioned in prompt.

1. Outpainting: select Q mask and invert it to select outside of image. give prompt: "outpaint this image" it will outpaint it or else *upscale to canvas width*..

for perfect out painting results: Create a canvas of let's say 1280 * 720 and in middle upload a photo (with bit blur optional). export to png with white background. go to nano banana and type: fill this image. 

in GIMP, just send entire image to nano banana with same prompt: fill this image/out paint this image 



#### Outpainting: Ultra realistic photograph of an original scene seamlessly extended through zooming out and outpainting the background. The original subject(s) remain perfectly consistent in appearance, pose, and lighting, now positioned within a larger, dynamically expanded environment. The outpainted background maintains photorealistic continuity with the original scene’s lighting, color palette, and perspective, seamlessly blending natural elements (e.g., terrain, architecture, or foliage) to create depth and context. Ultra high-resolution details reveal textures consistent with the original (e.g., fabric, skin, or surfaces), while sharp focus on the subject(s) ensures clarity against a softly blurred background. Natural lighting casts consistent shadows and highlights across the entire frame, with atmospheric haze enhancing depth in distant areas. 8k resolution, 35mm wide-angle lens for expansive perspective, deep depth of field, photorealistic color grading, and environmental coherence between original and extended regions.  \n\n### Key Enhancements:  \n1. **Seamless Integration**: Explicitly demands consistency in lighting, colors, and perspective between the original scene and outpainted background.  \n2. **Character Consistency**: Emphasizes preservation of subject details (appearance, pose, lighting) when zooming out.  \n3. **Photorealistic Depth**: Uses wide-angle lens (35mm) and atmospheric haze to amplify the "zoomed-out" effect while maintaining realism.  \n4. **Textural Continuity**: Ensures background elements (e.g., terrain, foliage) match the original scene’s textures (e.g., fabric, skin).  \n5. **Technical Precision**: Specifies 8k resolution, deep depth of field, and natural lighting to elevate realism.  \n\nThis prompt ensures AI tools like MidJourney or Stable Diffusion prioritize both **background expansion** and **character integrity** while delivering photorealistic quality.

2. Upscaling (place subject image in a white canvas that is 3 x bigger): select Q mask and dont invert it to select image. give prompt: "upscale  image, hi resolution" it will upscale it to canvas width.. very important: press ctrl + shift + z on gemini edit layer. it will expan the generated image to highest of resolution


3. Inpaint + Upscaler (place subject image in a white canvas that is 3 x bigger): same as point 2 upscaling.. without inverting selection, just write your prompt without keywords like Upscale " futuristic city, cars " it will select subject and blend to this theme.  press Ctrl + shift+ z to get this beautiful inpainted auto Upscaled photo


4. Similar Style Reference Image: Same selection as above with inverting it to outside of image. give prompt: "Fill this image coherently" will make similar style image.


Shortcut:

1. To view full scale of  gemini output image: click shift + s it will preview image. Then press ctrl + c and ctrl + shift + v to paste full scale output to a new window.  
