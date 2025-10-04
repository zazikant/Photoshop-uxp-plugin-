#!/usr/bin/env python
# -*- coding: utf-8 -*-

from gimpfu import *
import urllib2
import json
import base64
import tempfile
import os
import ssl

# 🔑 Your real API key
GEMINI_API_KEY = ""

def gemini_generate_image(image, drawable, prompt):
    try:
        pdb.gimp_progress_init("Generating image with Gemini...", None)
        
        # ✅ Correct model name
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key=" + GEMINI_API_KEY

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }

        # Bypass SSL for GIMP 2.10 on Windows
        import ssl
        if hasattr(ssl, '_create_unverified_context'):
            ssl._create_default_https_context = ssl._create_unverified_context

        req = urllib2.Request(
            url,
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'}
        )
        response = urllib2.urlopen(req)
        result = json.loads(response.read())

        image_b64 = None
        for candidate in result.get('candidates', []):
            for part in candidate.get('content', {}).get('parts', []):
                if 'inlineData' in part:
                    image_b64 = part['inlineData']['data']
                    break

        if not image_b64:
            pdb.gimp_message("⚠️ No image returned. Try a simple prompt like 'a red apple'.")
            return

        # Save to temp file
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_path = temp_file.name
        temp_file.close()  # 👈 Explicitly close the file handle

        with open(temp_path, 'wb') as f:
            f.write(base64.b64decode(image_b64))

        # Load into GIMP
        new_image = pdb.gimp_file_load(temp_path, temp_path)
        pdb.gimp_display_new(new_image)

        # Delete temp file
        os.unlink(temp_path)  # ✅ Now safe to delete

        pdb.gimp_message("✅ Image generated successfully!")
        
    except Exception as e:
        pdb.gimp_message("❌ Error: " + str(e))

register(
    "python_fu_gemini_generate_image",
    "Generate Image with Gemini",
    "Create image from text using Gemini AI",
    "You",
    "You",
    "2025",
    "<Image>/Filters/Gemini/Generate New Image...",
    "",
    [(PF_STRING, "prompt", "Prompt:", "a red apple on white background")],
    [],
    gemini_generate_image
)

main()