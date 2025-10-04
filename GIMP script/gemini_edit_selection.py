#!/usr/bin/env python
# -*- coding: utf-8 -*-

from gimpfu import *
import urllib2
import json
import base64
import tempfile
import os
import ssl

# 🔑 Replace with your key
GEMINI_API_KEY = ""

def edit_selection(image, drawable, prompt):
    if pdb.gimp_selection_is_empty(image):
        pdb.gimp_message("⚠️ Make a selection first (use Quick Mask for soft edges)!")
        return

    try:
        pdb.gimp_progress_init("Editing with Gemini...", None)
        non_empty, x1, y1, x2, y2 = pdb.gimp_selection_bounds(image)
        w, h = x2 - x1, y2 - y1
        pdb.gimp_message("Debug Info: Placing result at coordinates ({}, {}).".format(x1, y1))

        # Duplicate image
        dup = pdb.gimp_image_duplicate(image)
        layer = pdb.gimp_image_get_active_layer(dup)

        # Ensure alpha
        if not pdb.gimp_drawable_has_alpha(layer):
            pdb.gimp_layer_add_alpha(layer)

        # Apply selection as transparency (soft edges preserved!)
        mask = pdb.gimp_layer_create_mask(layer, ADD_SELECTION_MASK)
        pdb.gimp_layer_add_mask(layer, mask)
        pdb.gimp_layer_remove_mask(layer, 0)  # Apply the mask (0 = MASK_APPLY)

        # Crop to selection bounds
        pdb.gimp_image_crop(dup, w, h, x1, y1)

        # Export with alpha
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_path = temp_file.name
        temp_file.close()
        pdb.file_png_save_defaults(dup, layer, temp_path, temp_path)
        with open(temp_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read())
        os.unlink(temp_path)
        pdb.gimp_image_delete(dup)

        # Call Gemini
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key=" + GEMINI_API_KEY
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/png", "data": img_b64}}
                ]
            }]
        }

        if hasattr(ssl, '_create_unverified_context'):
            ssl._create_default_https_context = ssl._create_unverified_context

        req = urllib2.Request(
            url, 
            data=json.dumps(payload), 
            headers={'Content-Type': 'application/json'}
        )
        resp = urllib2.urlopen(req)
        data = json.loads(resp.read())

        # Get result image
        result_b64 = None
        for cand in data.get('candidates', []):
            for part in cand.get('content', {}).get('parts', []):
                if 'inlineData' in part:
                    result_b64 = part['inlineData']['data']
                    break

        if not result_b64:
            pdb.gimp_message("⚠️ No image returned.")
            return

        # Load result
        temp_file2 = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        with open(temp_file2.name, 'wb') as f:
            f.write(base64.b64decode(result_b64))
        result_layer = pdb.gimp_file_load_layer(image, temp_file2.name)
        pdb.gimp_image_insert_layer(image, result_layer, None, 0)
        pdb.gimp_item_set_name(result_layer, "Gemini Edit")
        pdb.gimp_layer_translate(result_layer, x1, y1)

        # Scale if needed
        lw = pdb.gimp_drawable_width(result_layer)
        lh = pdb.gimp_drawable_height(result_layer)
        if lw != w or lh != h:
            pdb.gimp_layer_scale(result_layer, w, h, False)

        os.unlink(temp_file2.name)
        pdb.gimp_message("✅ Edit complete!")

    except Exception as e:
        pdb.gimp_message("❌ " + str(e))

register(
    "python_fu_gemini_edit_selection",
    "Edit Selection with Gemini",
    "Edit selected area using Gemini AI (supports soft edges)",
    "You",
    "You",
    "2025",
    "<Image>/Filters/Gemini/Edit Selection...",
    "RGB*, GRAY*",
    [(PF_STRING, "prompt", "Prompt:", "replace with a futuristic cityscape")],
    [],
    edit_selection
)

main()
