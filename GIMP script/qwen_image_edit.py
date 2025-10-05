
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#  GIMP 3 Plug-in for Qwen Image Editing
# Version: 1.3 (Final Corrected)
# Author: Gemini & Contributors
# Date: 2025-10-05
# Description: Sends a user's selection to the Qwen Image Edit API and
#              replaces it with the generated result on a new layer.

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GObject, GLib
import sys

import base64
import os
import tempfile
from urllib.request import urlopen
from urllib.error import URLError

# --- Dependency Check ---
try:
    import dashscope
    from dashscope import MultiModalConversation
    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False

# --- CONFIGURATION ---
# 🔑 IMPORTANT: Replace with your actual Dashscope API key.
# It is recommended to use an environment variable for better security.
DASHSCOPE_API_KEY = ""

# The correct API endpoint URL without any trailing spaces.
DASHSCOPE_ENDPOINT = "https://dashscope-intl.aliyuncs.com/api/v1"
# --- END CONFIGURATION ---


def qwen_edit_selection(procedure, run_mode, args, data):
    """
    Main function for the GIMP plug-in procedure.
    """
    # GIMP 3: Extract arguments from Gimp.ValueArray using typed getters.
    image = args.get_image(0)
    drawable = args.get_drawable(1)
    prompt = args.get_string(2)

    # --- Pre-flight Checks ---
    if not DASHSCOPE_AVAILABLE:
        msg = "❌ The 'dashscope' library is not found! Please install it in GIMP's Python environment."
        Gimp.message(msg)
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(msg))

    api_key = DASHSCOPE_API_KEY or os.environ.get("DASHSCOPE_API_KEY")
    if not api_key or not api_key.strip():
        msg = "❌ API Key is not set. Please set DASHSCOPE_API_KEY in the script or as an environment variable."
        Gimp.message(msg)
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(msg))

    selection = image.get_selection()
    if selection.is_empty():
        msg = "⚠️ Please make a selection first. A soft-edged selection (e.g., using a Quick Mask) is recommended."
        Gimp.message(msg)
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(msg))

    Gimp.progress_init(f"Editing with Qwen: '{prompt}'...")

    try:
        dashscope.api_key = api_key.strip()
        dashscope.base_http_api_url = DASHSCOPE_ENDPOINT  # No need for .strip() now

        # --- Prepare Selection for API ---
        non_empty, x1, y1, x2, y2 = selection.get_bounds()
        if not non_empty:
            raise RuntimeError("Selection is empty after bounds check.")
        w, h = x2 - x1, y2 - y1

        # Duplicate the image to work on a copy.
        dup_image = image.duplicate()
        dup_layer = dup_image.get_active_layer()

        if not dup_layer:
             raise RuntimeError("Could not get the active layer from the duplicated image.")

        if not dup_layer.has_alpha():
            dup_layer.add_alpha()

        # Create a mask from the selection and apply it to make the unselected area transparent.
        mask = dup_layer.create_mask(Gimp.AddMaskType.SELECTION_MASK)
        dup_layer.add_mask(mask)
        dup_layer.remove_mask(Gimp.MaskApplyMode.APPLY)

        # Crop the duplicated image to the selection bounds.
        dup_image.crop(w, h, x1, y1)

        # Export the cropped selection to a temporary PNG file.
        temp_input_path = os.path.join(GLib.get_tmp_dir(), "gimp_qwen_input.png")

        # GIMP 3: Use the proper method to call a PDB procedure.
        pdb = Gimp.get_pdb()
        png_saver = pdb.lookup_procedure("file-png-save")
        config = png_saver.create_config()
        config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        config.set_property("image", dup_image)
        config.set_property("drawable", dup_layer)
        config.set_property("filename", temp_input_path)
        config.set_property("raw-filename", temp_input_path)
        result = png_saver.run(config)

        if result.index(0) != Gimp.PDBStatusType.SUCCESS:
            raise RuntimeError("Failed to save the temporary image for the API.")
        
        dup_image.delete()  # Clean up the duplicated image.

        # Read the temporary file and encode it in Base64.
        with open(temp_input_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')
        os.unlink(temp_input_path)

        # --- Call Qwen API ---
        Gimp.progress_set_text("Contacting Qwen API...")
        messages = [{
            "role": "user",
            "content": [
                {"image": "data:image/png;base64," + img_b64},
                {"text": prompt}
            ]
        }]
        
        response = MultiModalConversation.call(model="qwen-image-edit", messages=messages)

        if response.status_code != 200:
            raise RuntimeError(f"API Error ({response.status_code}): {getattr(response, 'message', 'Unknown error')}")

        output_url = response.output.choices[0].message.content[0]['image']

        # --- Process API Result ---
        Gimp.progress_set_text("Downloading generated image...")
        with urlopen(output_url) as resp:
            img_data = resp.read()

        temp_output_path = os.path.join(GLib.get_tmp_dir(), "gimp_qwen_output.png")
        with open(temp_output_path, 'wb') as f:
            f.write(img_data)

        # Load the resulting image as a new layer in the original image.
        result_layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, temp_output_path)
        if not result_layer:
            raise RuntimeError("Failed to load the generated image from the temporary file.")
        os.unlink(temp_output_path)
        
        result_layer.set_name(f"Qwen: {prompt[:30]}")
        image.insert_layer(result_layer, None, 0)  # Insert at the top.
        result_layer.translate(x1, y1)  # Move to the original selection position.

        # Ensure the new layer has the exact dimensions of the selection.
        if result_layer.get_width() != w or result_layer.get_height() != h:
            result_layer.scale(w, h, False)

        Gimp.message("✅ Qwen edit complete!")

    except URLError as e:
        msg = f"❌ Network Error: Could not connect to the API. Check your internet connection and the endpoint URL. Details: {e.reason}"
        Gimp.message(msg)
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(msg))
    except Exception as e:
        msg = f"❌ An unexpected error occurred: {str(e)}"
        Gimp.message(msg)
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    finally:
        Gimp.progress_end()

    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class QwenEditPlugin(Gimp.PlugIn):
    """
    GIMP Plug-in class definition.
    """
    def do_query_procedures(self):
        return ['python-fu-qwen-edit-selection']

    def do_create_procedure(self, name):
        procedure = Gimp.Procedure.new(
            self,
            name,
            Gimp.PDBProcType.PLUGIN,
            qwen_edit_selection,
            None
        )

        procedure.set_documentation(
            "Edit a selection using the Qwen Image Edit AI.",
            "Sends the selected image region and a text prompt to the Qwen API and replaces the selection with the generated result on a new layer.",
            name
        )
        procedure.set_menu_label("Edit Selection with Qwen...")
        procedure.set_attribution("Gemini & Contributors", "Gemini", "2025")
        procedure.add_menu_path(["<Image>", "Filters", "AI Tools"])

        # Correct GIMP 3 argument registration
        procedure.add_argument(
            "image",
            GObject.ParamSpec.object("image", "Image", "Input image", Gimp.Image.__gtype__, GObject.ParamFlags.READWRITE)
        )
        procedure.add_argument(
            "drawable",
            GObject.ParamSpec.object("drawable", "Drawable", "Input drawable (layer)", Gimp.Drawable.__gtype__, GObject.ParamFlags.READWRITE)
        )
        procedure.add_argument(
            "prompt",
            GObject.ParamSpec.string("prompt", "Prompt", "Text prompt for editing", "make it a futuristic cityscape", GObject.ParamFlags.READWRITE)
        )

        return procedure


# Entry point required by GIMP to register the plug-in.
Gimp.main(QwenEditPlugin.__gtype__, sys.argv)



✅ Final Checklist Before Use
 * GIMP Version: Ensure you have GIMP 3.0 or a newer version installed.
 * Install dashscope: Open a terminal or command prompt and install the required library into GIMP's Python environment. The exact command may vary by OS, but it will be similar to:
   * Windows: C:\Program Files\GIMP 3\Python\python.exe -m pip install "dashscope[oss]"
   * Linux (Flatpak): flatpak run --command=gimp-pip org.gimp.GIMP install "dashscope[oss]"
 * Set API Key: Open the .py script and replace the empty string "" in DASHSCOPE_API_KEY with your actual API key.
 * Install Plug-in: Place the saved .py file into your user plug-ins folder. You can find this folder in GIMP via Edit > Preferences > Folders > Plug-ins.
 * Restart GIMP: Close and reopen GIMP to load the new plug-in.
 * Find It: You should now find the tool under the Filters > AI Tools > Edit Selection with Qwen... menu.

