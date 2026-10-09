#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# GIMP 3 plug-in: Edit Selection with kie.ai (Grok Imagine Image 2.0)
#
# DEBUG build: every step is logged to ~/.gimp_kie_debug.log so failures
# can be diagnosed even when GIMP swallows them.
#
# The generated result is inserted as a plain new layer on top of the
# layer stack (no selection-derived layer mask / clipping), positioned
# over the selection bounds.
#
# Install: copy into
#   C:\Users\Asus\AppData\Roaming\GIMP\3.2\plug-ins\kie_image_edit\kie_image_edit.py
# then FULLY quit GIMP (check Task Manager for gimp*.exe) and reopen.

import base64
import json
import math
import os
import sys
import tempfile
import time
import traceback
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GObject, GLib

KIE_MODEL = "grok-imagine-image-2-0/image-edit"
JOBS_BASE = "https://api.kie.ai/api/v1"
UPLOAD_BASE = "https://kieai.redpandaai.co"
KEY_FILE  = os.path.expanduser("~/.kie_api_key")
LOG_FILE  = os.path.expanduser("~/.gimp_kie_debug.log")


def _log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[{}] {}\n".format(time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


_log("module kie_image_edit loaded (pid={})".format(os.getpid()))


def _read_key():
    key = os.environ.get("KIE_API_KEY", "").strip()
    if key:
        return key
    if os.path.isfile(KEY_FILE):
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def _save_key(key):
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key.strip() + "\n")


def _http_post_json(url, payload, api_key):
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def _http_get_json(url, api_key):
    req = Request(
        url,
        headers={"Authorization": "Bearer " + api_key},
        method="GET",
    )
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def upload_png_base64(file_path, api_key):
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    payload = {
        "base64Data": b64,
        "uploadPath": "images",
        "fileName": os.path.basename(file_path),
    }
    data = _http_post_json(UPLOAD_BASE + "/api/file-base64-upload", payload, api_key)
    if data.get("code") != 200 or not data.get("data", {}).get("downloadUrl"):
        raise RuntimeError("Upload failed: " + str(data))
    return data["data"]["downloadUrl"]


def submit_image_edit(api_key, image_url, prompt, aspect_ratio):
    payload = {
        "model": KIE_MODEL,
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "image_urls": [image_url],
        },
    }
    data = _http_post_json(JOBS_BASE + "/jobs/createTask", payload, api_key)
    if data.get("code") != 200:
        raise RuntimeError("createTask failed: " + str(data))
    return data["data"]["taskId"]


def poll_task(api_key, task_id, *, timeout_s=600):
    start = time.time()
    delay = 3.0
    while time.time() - start < timeout_s:
        info = _http_get_json(JOBS_BASE + "/jobs/recordInfo?taskId=" + task_id, api_key)
        data = info.get("data", {}) or {}
        state = data.get("state")
        if state == "success":
            return json.loads(data["resultJson"])
        if state == "fail":
            raise RuntimeError(
                "kie.ai task failed: code={} msg={}".format(
                    data.get("failCode"), data.get("failMsg")))
        time.sleep(delay)
        delay = min(delay * 1.5, 10.0)
    raise TimeoutError("kie.ai task did not complete in {} s".format(timeout_s))


def download_to(url, dest):
    with urlopen(url, timeout=120) as r:
        with open(dest, "wb") as f:
            f.write(r.read())


def _selection_bounds(image):
    """(non_empty, x1, y1, x2, y2) via Gimp.Selection.bounds (GIMP 3.2)."""
    vals = tuple(Gimp.Selection.bounds(image))
    _log("Gimp.Selection.bounds raw={!r}".format(vals))
    if len(vals) == 6:
        _, non_empty, x1, y1, x2, y2 = vals
    elif len(vals) == 5:
        non_empty, x1, y1, x2, y2 = vals
    elif len(vals) == 4:
        non_empty, x1, y1, x2, y2 = (True,) + vals
    else:
        raise RuntimeError(
            "Unexpected Gimp.Selection.bounds result: {!r}".format(vals))
    return non_empty, x1, y1, x2, y2


# KIE's published Grok Imagine Image 2.0 image-edit options.
# Use "auto" for arbitrary selection shapes; let KIE choose the output ratio.
SUPPORTED_RATIOS = ("auto", "1:1", "2:3", "3:2", "16:9", "9:16")


def _export_selection_to_png(image, bounds):
    """Export the visible composite with the Quick Mask selection as alpha."""
    non_empty, x1, y1, x2, y2 = bounds
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        raise RuntimeError("Invalid selection bounds")

    dup = image.duplicate()
    tmp_path = os.path.join(
        tempfile.gettempdir(),
        "gimp_kie_edit_{}.png".format(os.getpid()))
    try:
        # Mask the merged visible composite, not just one layer. This keeps
        # the Quick Mask's gray values as partial alpha in the uploaded PNG.
        layer = dup.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
        if layer is None:
            raise RuntimeError("Could not merge visible layers for export")
        if not layer.has_alpha():
            layer.add_alpha()

        if non_empty:
            mask = layer.create_mask(Gimp.AddMaskType.SELECTION)
            layer.add_mask(mask)
            layer.remove_mask(Gimp.MaskApplyMode.APPLY)

        dup.crop(w, h, x1, y1)

        from gi.repository import Gio
        ok = Gimp.file_save(
            Gimp.RunMode.NONINTERACTIVE, dup,
            Gio.File.new_for_path(tmp_path))
        if not ok:
            raise RuntimeError("Failed to write temporary PNG")
    finally:
        dup.delete()

    return tmp_path, x1, y1, w, h


def _fit_layer_to_bounds(layer, w, h):
    """Fill w x h without stretching; center-crop only if ratios differ."""
    src_w, src_h = layer.get_width(), layer.get_height()
    if src_w <= 0 or src_h <= 0 or w <= 0 or h <= 0:
        raise RuntimeError("Invalid result or selection dimensions")

    # Scale uniformly to cover the target bounds, then crop to exact bounds.
    factor = max(w / float(src_w), h / float(src_h))
    scaled_w = max(w, int(math.ceil(src_w * factor)))
    scaled_h = max(h, int(math.ceil(src_h * factor)))

    # Scale at the origin, then position the finished layer later.
    layer.set_offsets(0, 0)
    if scaled_w != src_w or scaled_h != src_h:
        if not layer.scale(scaled_w, scaled_h, False):
            raise RuntimeError("Could not scale generated result layer")

    crop_left = (scaled_w - w) // 2
    crop_top = (scaled_h - h) // 2
    if scaled_w != w or scaled_h != h:
        if not layer.resize(w, h, -crop_left, -crop_top):
            raise RuntimeError("Could not crop result to selection bounds")


def _insert_result_layer(image, result_path, x1, y1, w, h, name):
    """Insert the result as a plain new layer on top of the stack.

    No selection-derived layer mask is applied: the full generated
    result is pasted outside/above any clipping, positioned over the
    original selection bounds.
    """
    from gi.repository import Gio
    image.undo_group_start()
    try:
        layer = Gimp.file_load_layer(
            Gimp.RunMode.NONINTERACTIVE, image,
            Gio.File.new_for_path(result_path))
        if layer is None:
            raise RuntimeError("Could not load generated result layer")
        _log("result layer {}x{} vs selection {}x{}".format(
            layer.get_width(), layer.get_height(), w, h))
        layer.set_name(name)
        image.insert_layer(layer, None, 0)

        # Match the selection rectangle without non-uniform stretching.
        _fit_layer_to_bounds(layer, w, h)
        layer.set_offsets(x1, y1)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()


def _image_alive(image):
    """True if the image reference is still usable."""
    if image is None:
        return False
    try:
        image.get_width()
        return True
    except Exception:
        return False


def _open_in_new_window(png_path):
    """Load png_path as a new image and give it a display.
    Returns True if displayed, False if the file could not be shown."""
    from gi.repository import Gio
    new_image = Gimp.file_load(
        Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(png_path))
    _log("file_load ok (new image created)")

    shown = False
    try:
        Gimp.display_new(new_image)
        shown = True
        _log("Gimp.display_new ok")
    except Exception as e:
        _log("Gimp.display_new failed: " + repr(e))
        try:
            pdb = Gimp.get_pdb()
            proc = pdb.lookup_procedure("gimp-display-new")
            cfg = proc.create_config()
            cfg.set_property("image", new_image)
            proc.run(cfg)
            shown = True
            _log("display via PDB ok")
        except Exception as e2:
            _log("PDB gimp-display-new failed: " + repr(e2))
    Gimp.displays_flush()
    return shown


class KieImageEdit(Gimp.PlugIn):

    def do_query_procedures(self):
        _log("do_query_procedures called (image_edit)")
        return ["kie-image-edit"]

    def do_set_i18n(self, name):
        return False

    def do_create_procedure(self, name):
        _log("do_create_procedure called for " + str(name))
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(
            Gimp.ProcedureSensitivityMask.DRAWABLE |
            Gimp.ProcedureSensitivityMask.NO_DRAWABLES)

        procedure.set_menu_label("Edit Selection with kie.ai (Grok)...")
        procedure.add_menu_path('<Image>/Filters/AI Tools/')

        procedure.set_documentation(
            "Send the user's selection to kie.ai Grok Imagine image-edit.",
            "Crops the current selection, uploads the PNG to kie.ai, POSTs "
            "the URL + prompt + aspect ratio, polls for completion, and "
            "inserts the result as a new layer.",
            name,
        )
        procedure.set_attribution("Kie GIMP Plugin", "Kie GIMP Plugin", "2026")

        procedure.add_string_argument(
            "prompt", "Prompt", "Describe the edit you want",
            "replace the background with a sunset beach",
            GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "aspect_ratio", "Aspect ratio",
            "auto (recommended), 1:1, 2:3, 3:2, 16:9, 9:16",
            "auto", GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "api_key", "API key",
            "kie.ai API key. Saved to ~/.kie_api_key after first run.",
            _read_key(),
            GObject.ParamFlags.READWRITE,
        )
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        _log("run() entered (image_edit), run_mode={!r}".format(run_mode))

        try:
            if run_mode == Gimp.RunMode.INTERACTIVE:
                _log("INTERACTIVE: importing GimpUi...")
                gi.require_version('GimpUi', '3.0')
                from gi.repository import GimpUi
                _log("GimpUi imported, calling GimpUi.init...")
                GimpUi.init("kie_image_edit")

                _log("creating ProcedureDialog...")
                dialog = GimpUi.ProcedureDialog.new(
                    procedure, config, "Edit Selection with kie.ai (Grok)")
                try:
                    GimpUi.window_set_transient(dialog)
                except Exception as e:
                    _log("window_set_transient failed (non-fatal): " + repr(e))

                _log("filling dialog with prompt/aspect_ratio/api_key...")
                dialog.fill(["prompt", "aspect_ratio", "api_key"])

                _log("showing dialog (dialog.run())...")
                ok = dialog.run()
                _log("dialog.run() returned {!r}".format(ok))
                dialog.destroy()
                if not ok:
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.CANCEL, None)
            else:
                _log("non-interactive run_mode; skipping dialog")
        except Exception:
            _log("DIALOG FAILED with exception:\n" + traceback.format_exc())
            # Fall through so the rest still runs with defaults/current config

        prompt       = (config.get_property("prompt") or "").strip()
        aspect_ratio = (config.get_property("aspect_ratio") or "").strip() or "auto"
        api_key      = (config.get_property("api_key") or "").strip()

        _log("prompt={!r} aspect_ratio={!r} api_key={}".format(
            prompt, aspect_ratio, "(set)" if api_key else "(empty)"))

        if not api_key:
            api_key = _read_key()
        if not api_key:
            msg = ("No API key. Paste your kie.ai key into the 'API key' "
                   "field of the dialog and press OK. "
                   "(See ~/.gimp_kie_debug.log if no dialog appeared.)")
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(msg))

        if not prompt:
            msg = "Prompt is empty. Describe the edit you want."
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(msg))

        aspect_ratio = aspect_ratio.lower()
        if aspect_ratio not in SUPPORTED_RATIOS:
            msg = ("Unsupported aspect ratio. Use: " +
                   ", ".join(SUPPORTED_RATIOS))
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(msg))

        _save_key(api_key)

        if not _image_alive(image):
            msg = ("The image this plug-in was started with is no longer "
                   "open. Keep the image open while the edit runs.")
            _log("image invalid at run() start")
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(msg))

        tmp_path = None
        result_path = None
        try:
            non_empty, x1, y1, x2, y2 = _selection_bounds(image)
            if not non_empty:
                x1, y1 = 0, 0
                x2 = image.get_width()
                y2 = image.get_height()
            bounds = (non_empty, x1, y1, x2, y2)
            _log("selection bounds={!r}".format(bounds))

            _log("using KIE aspect ratio={!r} for selection {}x{}".format(
                aspect_ratio, x2 - x1, y2 - y1))

            Gimp.progress_init("kie.ai: exporting selection...")
            tmp_path, x1, y1, w, h = _export_selection_to_png(image, bounds)
            _log("exported PNG: " + tmp_path)

            Gimp.progress_init("kie.ai: uploading image...")
            image_url = upload_png_base64(tmp_path, api_key)
            _log("uploaded: " + image_url)

            Gimp.progress_init("kie.ai: submitting edit...")
            task_id = submit_image_edit(api_key, image_url, prompt, aspect_ratio)
            _log("task_id=" + str(task_id))

            Gimp.progress_init("kie.ai: generating...")
            result = poll_task(api_key, task_id)
            urls = result.get("resultUrls") or []
            _log("resultUrls count={}".format(len(urls)))
            if not urls:
                raise RuntimeError("kie.ai returned no resultUrls")

            Gimp.progress_init("kie.ai: downloading result...")
            result_path = os.path.join(
                tempfile.gettempdir(),
                "gimp_kie_result_{}.png".format(os.getpid()))
            download_to(urls[0], result_path)
            _log("downloaded to " + result_path)

            if _image_alive(image):
                _log("image still valid; inserting as new layer "
                     "(no selection mask, plain paste)...")
                _insert_result_layer(
                    image, result_path, x1, y1, w, h,
                    "kie: " + prompt[:30])
                _log("inserted as new layer; DONE")
                Gimp.message("✅ kie.ai image-edit complete.")
            else:
                _log("image was closed during generation; "
                     "opening result in a new window instead")
                shown = _open_in_new_window(result_path)
                if shown:
                    Gimp.message(
                        "✅ kie.ai edit complete, but the image was closed "
                        "during generation — result opened in a new window.")
                    _log("DONE (new window fallback)")
                else:
                    Gimp.message(
                        "✅ Generated, but image closed and no display "
                        "could be opened. Image saved at: " + result_path)
                    result_path = None  # keep the file for the user
        except (URLError, HTTPError, KeyError, RuntimeError, TimeoutError,
                GLib.Error) as e:
            _log("FAILED: " + repr(e))
            msg = "❌ kie.ai image-edit failed: " + str(e)
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(msg))
        except Exception as e:
            _log("UNEXPECTED FAILURE:\n" + traceback.format_exc())
            msg = "❌ kie.ai image-edit failed (unexpected): " + repr(e)
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(msg))
        finally:
            for p in (tmp_path, result_path):
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


Gimp.main(KieImageEdit.__gtype__, sys.argv)
