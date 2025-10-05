below script is not tested. 

✅ Final Checklist Before Use
[ ] GIMP 3.0+ installed, works on python 3
[ ] dashscope[oss] installed in GIMP’s Python environment
[ ] API key set in script
[ ] Script placed in user plug-ins folder
[ ] GIMP restarted




#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GObject, GLib
import sys # Required for the Gimp.main entry point

import base64
import os
import tempfile
from urllib.request import urlopen

# Try to import dashscope
try:
    import dashscope
    from dashscope import MultiModalConversation
    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False

# --- CONFIGURATION ---
DASHSCOPE_API_KEY = ""  # 🔑 Replace with your API key!
DASHSCOPE_ENDPOINT = "https://dashscope-intl.aliyuncs.com/api/v1"
# --- END CONFIGURATION ---

def qwen_edit_selection(procedure, run_mode, args, data):
    # GIMP 3: Extract arguments from the Gimp.ValueArray by index
    image = args.index(0)
    drawable = args.index(1)
    prompt = args.index(2)

    # --- Pre-flight checks ---
    if not DASHSCOPE_AVAILABLE:
        Gimp.message("❌ dashscope library not found! Install it in GIMP's Python environment.")
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())

    if not DASHSCOPE_API_KEY.strip():
        Gimp.message("❌ Please set your DASHSCOPE_API_KEY in the script!")
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())

    selection = image.get_selection()
    if selection.is_empty():
        Gimp.message("⚠️ Make a selection first (Quick Mask recommended for soft edges)!")
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())

    Gimp.progress_init(f"Editing with Qwen: '{prompt}'...")

    try:
        dashscope.api_key = DASHSCOPE_API_KEY
        dashscope.base_http_api_url = DASHSCOPE_ENDPOINT

        # Get selection bounds
        non_empty, x1, y1, x2, y2 = selection.get_bounds()
        if not non_empty:
            raise RuntimeError("Selection is empty")
        w, h = x2 - x1, y2 - y1

        # Duplicate image and isolate selection
        dup_image = image.duplicate()
        dup_layer = dup_image.get_active_layer()

        if not dup_layer.has_alpha():
            dup_layer.add_alpha()

        # Apply selection as transparency
        mask = dup_layer.create_mask(Gimp.AddMaskType.SELECTION_MASK)
        dup_layer.add_mask(mask)
        dup_layer.remove_mask(Gimp.MaskApplyMode.APPLY)

        # Crop to selection
        dup_image.crop(w, h, x1, y1)

        # Export to temp PNG using the correct PDB call
        temp_input = os.path.join(GLib.get_tmp_dir(), "gimp_qwen_input.png")
        pdb = Gimp.get_pdb()
        result = pdb.run_procedure(
            "file-png-save",
            [
                Gimp.RunMode.NONINTERACTIVE,
                dup_image,
                dup_layer,
                temp_input,
                temp_input
            ]
        )
        if result.index(0) != Gimp.PDBStatusType.SUCCESS:
            raise RuntimeError("Failed to save temporary image")

        dup_image.delete()

        # Encode image
        with open(temp_input, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')
        os.unlink(temp_input)

        # Call Qwen API
        messages = [{
            "role": "user",
            "content": [
                {"image": "data:image/png;base64," + img_b64},
                {"text": prompt}
            ]
        }]

        response = MultiModalConversation.call(
            model="qwen-image-edit",
            messages=messages,
            api_key=DASHSCOPE_API_KEY
        )

        if response.status_code != 200:
            raise RuntimeError(f"API Error ({response.status_code}): {getattr(response, 'message', 'Unknown')}")

        output_url = response.output.choices[0].message.content[0]['image']

        # Download result
        with urlopen(output_url) as resp:
            img_data = resp.read()

        temp_output = os.path.join(GLib.get_tmp_dir(), "gimp_qwen_output.png")
        with open(temp_output, 'wb') as f:
            f.write(img_data)

        # Load result as new layer using the correct GIMP 3 function
        result_layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, temp_output)
        if not result_layer:
            raise RuntimeError("Failed to load result image")

        result_layer.set_name("Qwen Edit")
        image.insert_layer(result_layer, None, 0)
        result_layer.translate(x1, y1)

        if result_layer.get_width() != w or result_layer.get_height() != h:
            result_layer.scale(w, h, False)

        os.unlink(temp_output)
        Gimp.message("✅ Qwen edit complete!")

    except Exception as e:
        Gimp.message(f"❌ Error: {str(e)}")
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    finally:
        Gimp.progress_end()

    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class QwenEditPlugin(Gimp.PlugIn):
    def do_query_procedures(self):
        return ['python-fu-qwen-edit-selection']

    def do_create_procedure(self, name):
        procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, qwen_edit_selection, None)

        procedure.set_documentation(
            "Edit selection using Qwen Image Edit AI",
            "Sends selected region to Qwen API with prompt and replaces it with AI-generated result.",
            name
        )
        procedure.set_menu_label("Edit Selection with Qwen...")
        procedure.set_attribution("Your Name", "Your Name", "2025")
        procedure.add_menu_path(["<Image>", "Filters", "Qwen"])

        procedure.add_argument(
            "image", GObject.ParamSpec.object("image", "Image", "Input image", Gimp.Image.__gtype__, GObject.ParamFlags.READWRITE)
        )
        procedure.add_argument(
            "drawable", GObject.ParamSpec.object("drawable", "Drawable", "Input drawable (layer)", Gimp.Drawable.__gtype__, GObject.ParamFlags.READWRITE)
        )
        procedure.add_argument(
            "prompt", GObject.ParamSpec.string("prompt", "Prompt", "Text prompt for editing", "replace with a futuristic cityscape", GObject.ParamFlags.READWRITE)
        )

        return procedure


# Entry point
Gimp.main(QwenEditPlugin.__gtype__, Gimp.main_version(), sys.modules[__name__])