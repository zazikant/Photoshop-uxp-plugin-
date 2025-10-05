-----Below script is not tested-----


Here's the complete modified GIMP plugin script for Qwen Image Edit API:

#!/usr/bin/env python
# -*- coding: utf-8 -*-
from gimpfu import *
import json
import base64
import tempfile
import os
try:
    import dashscope
    from dashscope import MultiModalConversation
    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False
# 🔑 Replace with your DashScope API key
DASHSCOPE_API_KEY = ""
# Set region endpoint (choose one):
# Singapore: https://dashscope-intl.aliyuncs.com/api/v1
# Beijing: https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_ENDPOINT = "https://dashscope-intl.aliyuncs.com/api/v1"
def edit_selection(image, drawable, prompt):
    if not DASHSCOPE_AVAILABLE:
        pdb.gimp_message("❌ dashscope library not installed! Run: pip install dashscope --upgrade")
        return
    
    if not DASHSCOPE_API_KEY:
        pdb.gimp_message("❌ Please set your DASHSCOPE_API_KEY in the script!")
        return
    
    if pdb.gimp_selection_is_empty(image):
        pdb.gimp_message("⚠️ Make a selection first (use Quick Mask for soft edges)!")
        return
    try:
        pdb.gimp_progress_init("Editing with Qwen...", None)
        
        # Set the DashScope endpoint
        dashscope.base_http_api_url = DASHSCOPE_ENDPOINT
        
        # Get selection bounds
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
        
        # Read and encode image
        with open(temp_path, 'rb') as f:
            img_data = f.read()
            img_b64 = base64.b64encode(img_data).decode('utf-8')
        
        os.unlink(temp_path)
        pdb.gimp_image_delete(dup)
        # Prepare Qwen API request using DashScope format
        messages = [
            {
                "role": "user",
                "content": [
                    {"image": "data:image/png;base64," + img_b64},
                    {"text": prompt}
                ]
            }
        ]
        # Call Qwen Image Edit API
        response = MultiModalConversation.call(
            api_key=DASHSCOPE_API_KEY,
            model="qwen-image-edit",
            messages=messages,
            stream=False,
            watermark=False,
            negative_prompt=""
        )
        # Check response status
        if response.status_code != 200:
            pdb.gimp_message("❌ API Error: {}".format(response.message))
            return
        # Extract result image from response
        result_b64 = None
        try:
            # DashScope response structure: response.output.choices[0].message.content[0]['image']
            output_url = response.output.choices[0].message.content[0]['image']
            
            # Download the image from URL
            import urllib2
            img_response = urllib2.urlopen(output_url)
            img_data = img_response.read()
            
            # Save to temporary file
            temp_file2 = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_path2 = temp_file2.name
            temp_file2.write(img_data)
            temp_file2.close()
            
        except Exception as e:
            pdb.gimp_message("❌ Failed to extract result image: {}".format(str(e)))
            return
        # Load result into GIMP
        result_layer = pdb.gimp_file_load_layer(image, temp_path2)
        pdb.gimp_image_insert_layer(image, result_layer, None, 0)
        pdb.gimp_item_set_name(result_layer, "Qwen Edit")
        # Force a UI update before trying to move the layer
        pdb.gimp_displays_flush()
        # Set the layer's final position
        pdb.gimp_layer_translate(result_layer, x1, y1)
        # Another flush for good measure
        pdb.gimp_displays_flush()
        # Scale if needed to match original selection
        lw = pdb.gimp_drawable_width(result_layer)
        lh = pdb.gimp_drawable_height(result_layer)
        if lw != w or lh != h:
            pdb.gimp_layer_scale(result_layer, w, h, False)
        # Clean up
        os.unlink(temp_path2)
        pdb.gimp_message("✅ Edit complete!")
    except Exception as e:
        pdb.gimp_message("❌ Error: {}".format(str(e)))
register(
    "python_fu_qwen_edit_selection",
    "Edit Selection with Qwen",
    "Edit selected area using Qwen Image Edit AI (supports soft edges)",
    "You",
    "You",
    "2025",
    "<Image>/Filters/Qwen/Edit Selection...",
    "RGB*, GRAY*",
    [(PF_STRING, "prompt", "Prompt:", "replace with a futuristic cityscape")],
    [],
    edit_selection
)
main()
Key changes from Gemini to Qwen:

Import: Uses dashscope library instead of urllib2 for API calls
API Endpoint: Configurable DashScope endpoint (Singapore or Beijing region)
Message Format: Uses Qwen's message structure with role: user and content array containing image and text
Image Input: Base64 data URI format (data:image/png;base64,{data})
Model Name: Uses "qwen-image-edit" model
Parameters: Includes watermark=False and negative_prompt="" parameters
Response Handling: Extracts image URL from DashScope response structure and downloads it
Menu Location: Changed from Filters/Gemini/ to Filters/Qwen/
Installation instructions:

pip install dashscope --upgrade
Save this as qwen_edit_selection.py in your GIMP plugins folder (e.g., C:\Users\Asus\AppData\Roaming\GIMP\2.10\plug-ins).

