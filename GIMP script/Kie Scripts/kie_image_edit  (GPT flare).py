#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# GIMP 3 plug-in: Edit Selection with kie.ai (GPT Image 2.5 Flare)  [HARDENED]
#
# DEBUG build: every step is logged to ~/.gimp_kie_debug.log so failures
# can be diagnosed even when GIMP swallows them.
#
# The generated result is inserted as a plain new layer on top of the
# layer stack (no selection-derived layer mask / clipping), positioned
# over the selection bounds.
#
# Hardening:
#   - ASCII sanitizer: kie.ai responses are translated to pure ASCII so
#     GIMP's latin-1 error display path cannot crash with UnicodeEncodeError.
#   - _normalize_key: strips surrounding whitespace, surrounding quotes,
#     and a leading 'Bearer ' prefix the user may have pasted along
#     with the actual token.
#   - GLib.Error constructed via new_literal(quark, msg, 0).
#   - Detailed HTTP logging: every request logs method, URL, status,
#     body length; on HTTPError, the response body is captured into
#     the log so the actual kie.ai error payload is visible.
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
import unicodedata
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GObject, GLib

# ---------------------------------------------------------------------------
# gpt-image-2-5-flare image-to-image model identifier (kie.ai createTask sample)
# ---------------------------------------------------------------------------
KIE_MODEL = "gpt-image-2-5-flare-image-to-image"

JOBS_BASE = "https://api.kie.ai/api/v1"
UPLOAD_BASE = "https://kieai.redpandaai.co"
KEY_FILE  = os.path.expanduser("~/.kie_api_key")
LOG_FILE  = os.path.expanduser("~/.gimp_kie_debug.log")

KIE_ERROR_QUARK = "kie-plugin-error"


def _log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[{}] {}\n".format(time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


_log("module kie_image_edit (gpt-image-2-5-flare) loaded (pid={})".format(os.getpid()))


def _ascii_safe(text):
    """Coerce any string to pure ASCII safe for GIMP's latin-1 paths."""
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return repr(text)
    text = unicodedata.normalize("NFKC", text)
    table = {
        0x2010: "-",   0x2011: "-",   0x2012: "-",   0x2013: "-",
        0x2014: "--",  0x2018: "'",   0x2019: "'",   0x201A: ",",
        0x201C: '"',   0x201D: '"',   0x2026: "...", 0x00A0: " ",
    }
    text = text.translate(table)
    out = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
        else:
            out.append("[U+{:04X}]".format(ord(ch)))
    return "".join(out)


def _normalize_key(key):
    """Strip whitespace, surrounding quotes, and any leading 'Bearer '."""
    if not key:
        return ""
    key = key.strip().strip('"').strip("'").strip()
    low = key.lower()
    if low.startswith("bearer "):
        key = key[len("bearer "):].lstrip()
    elif low.startswith("bearer\t"):
        key = key[len("bearer\t"):].lstrip()
    return key


def _read_key():
    key = os.environ.get("KIE_API_KEY", "").strip()
    if key:
        return _normalize_key(key)
    if os.path.isfile(KEY_FILE):
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            return _normalize_key(f.read().strip())
    return ""


def _save_key(key):
    key = _normalize_key(key)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key + "\n")


def _make_glib_error(message):
    """Build a GLib.Error the correct way."""
    safe_msg = _ascii_safe(message)
    try:
        quark = GLib.quark_from_string(KIE_ERROR_QUARK)
        return GLib.Error.new_literal(quark, safe_msg, 0)
    except Exception as e:
        _log("GLib.Error.new_literal failed ({}); falling back".format(repr(e)))
        try:
            return GLib.Error(safe_msg)
        except Exception:
            return GLib.Error()


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
    _log("POST {} (auth_len={}, body_len={})".format(
        url, len(api_key), len(body)))
    try:
        with urlopen(req, timeout=120) as resp:
            raw = resp.read()
            _log("POST {} -> HTTP {} ({} bytes)".format(
                url, resp.status, len(raw)))
            return json.loads(raw)
    except HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = "<unreadable>"
        _log("POST {} -> HTTPError {} body={}".format(
            url, e.code, err_body[:1000]))
        raise


def _http_get_json(url, api_key):
    req = Request(
        url,
        headers={"Authorization": "Bearer " + api_key},
        method="GET",
    )
    _log("GET {}".format(url))
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read()
            _log("GET {} -> HTTP {} ({} bytes)".format(
                url, resp.status, len(raw)))
            return json.loads(raw)
    except HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = "<unreadable>"
        _log("GET {} -> HTTPError {} body={}".format(
            url, e.code, err_body[:1000]))
        raise


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
        raise RuntimeError("Upload failed: " + json.dumps(
            data, ensure_ascii=True))
    return data["data"]["downloadUrl"]


def submit_image_edit(api_key, image_url, prompt, aspect_ratio,
                      resolution="4K", background="transparent"):
    """Submit a gpt-image-2-5-flare-image-to-image task.

    Per the kie.ai createTask sample, the input object uses:
      - prompt         (str)
      - input_urls     (list[str])   <- the uploaded image URL(s)
      - aspect_ratio   (str)         <- "auto", "1:1", ...
      - resolution     (str)         <- "1K", "2K", "4K"
      - background     (str)         <- "transparent" or "opaque"

    Note: gpt-image-2-5-flare uses 'input_urls' (NOT 'image_urls'
    like seedream, and NOT 'image_input' like nano-banana-2).
    """
    payload = {
        "model": KIE_MODEL,
        "input": {
            "prompt": prompt,
            "input_urls": [image_url],
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "background": background,
        },
    }
    data = _http_post_json(JOBS_BASE + "/jobs/createTask", payload, api_key)
    if data.get("code") != 200:
        raise RuntimeError("createTask failed: " + json.dumps(
            data, ensure_ascii=True))
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
                    data.get("failCode"), json.dumps(
                        data.get("failMsg"), ensure_ascii=True)))
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


# KIE's published gpt-image-2-5-flare aspect ratios.
SUPPORTED_RATIOS = ("auto", "1:1", "2:3", "3:2", "16:9", "9:16", "4:3", "3:4")

# gpt-image-2-5-flare supported resolutions.
SUPPORTED_RESOLUTIONS = ("1K", "2K", "4K")

# gpt-image-2-5-flare supported background modes.
SUPPORTED_BACKGROUNDS = ("transparent", "opaque", "white", "black")


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

    factor = max(w / float(src_w), h / float(src_h))
    scaled_w = max(w, int(math.ceil(src_w * factor)))
    scaled_h = max(h, int(math.ceil(src_h * factor)))

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
    """Load png_path as a new image and give it a display."""
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
        _log("do_query_procedures called (image_edit, flare)")
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

        procedure.set_menu_label("Edit Selection with kie.ai (GPT Image 2.5 Flare)...")
        procedure.add_menu_path('<Image>/Filters/AI Tools/')

        procedure.set_documentation(
            "Send the user's selection to kie.ai GPT Image 2.5 Flare image-to-image.",
            "Crops the current selection, uploads the PNG to kie.ai, POSTs "
            "the URL + prompt + aspect_ratio + resolution + background to "
            "the gpt-image-2-5-flare-image-to-image model, polls for "
            "completion, and inserts the result as a new layer.",
            name,
        )
        procedure.set_attribution("Kie GIMP Plugin", "Kie GIMP Plugin", "2026")

        procedure.add_string_argument(
            "prompt", "Prompt", "Describe the edit you want",
            "Transform this product image into a premium e-commerce poster style.",
            GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "aspect_ratio", "Aspect ratio",
            "auto, 1:1, 2:3, 3:2, 16:9, 9:16, 4:3, 3:4",
            "auto", GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "resolution", "Resolution",
            "Output resolution: 1K, 2K, or 4K",
            "4K", GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "background", "Background",
            "Background mode: transparent, opaque, white, or black",
            "transparent", GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "api_key", "API key",
            "kie.ai API key (no 'Bearer ' prefix). Saved to ~/.kie_api_key after first run.",
            _read_key(),
            GObject.ParamFlags.READWRITE,
        )
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        _log("run() entered (image_edit, flare), run_mode={!r}".format(run_mode))

        try:
            if run_mode == Gimp.RunMode.INTERACTIVE:
                _log("INTERACTIVE: importing GimpUi...")
                gi.require_version('GimpUi', '3.0')
                from gi.repository import GimpUi
                _log("GimpUi imported, calling GimpUi.init...")
                GimpUi.init("kie_image_edit")

                _log("creating ProcedureDialog...")
                dialog = GimpUi.ProcedureDialog.new(
                    procedure, config, "Edit Selection with kie.ai (GPT Image 2.5 Flare)")
                try:
                    GimpUi.window_set_transient(dialog)
                except Exception as e:
                    _log("window_set_transient failed (non-fatal): " + repr(e))

                _log("filling dialog with prompt/aspect_ratio/resolution/background/api_key...")
                dialog.fill(["prompt", "aspect_ratio", "resolution",
                             "background", "api_key"])

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

        prompt       = (config.get_property("prompt") or "").strip()
        aspect_ratio = (config.get_property("aspect_ratio") or "").strip() or "auto"
        resolution   = (config.get_property("resolution") or "").strip() or "4K"
        background   = (config.get_property("background") or "").strip() or "transparent"
        api_key_raw  = (config.get_property("api_key") or "").strip()
        api_key      = _normalize_key(api_key_raw) or _read_key()

        _log("prompt={!r} aspect_ratio={!r} resolution={!r} background={!r} "
             "api_key_len={} (raw_len={})".format(
                 prompt, aspect_ratio, resolution, background,
                 len(api_key), len(api_key_raw)))

        if not api_key:
            msg = ("No API key. Paste your kie.ai key into the 'API key' "
                   "field of the dialog and press OK. (Do NOT include the "
                   "'Bearer ' prefix - the plugin adds it automatically.)")
            Gimp.message(_ascii_safe(msg))
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, _make_glib_error(msg))

        if not prompt:
            msg = "Prompt is empty. Describe the edit you want."
            Gimp.message(_ascii_safe(msg))
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, _make_glib_error(msg))

        aspect_ratio = aspect_ratio.lower()
        if aspect_ratio not in SUPPORTED_RATIOS:
            msg = ("Unsupported aspect ratio. Use: " +
                   ", ".join(SUPPORTED_RATIOS))
            Gimp.message(_ascii_safe(msg))
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, _make_glib_error(msg))

        resolution = resolution.upper()
        if resolution not in SUPPORTED_RESOLUTIONS:
            msg = ("Unsupported resolution. Use: " +
                   ", ".join(SUPPORTED_RESOLUTIONS))
            Gimp.message(_ascii_safe(msg))
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, _make_glib_error(msg))

        background = background.lower()
        if background not in SUPPORTED_BACKGROUNDS:
            msg = ("Unsupported background. Use: " +
                   ", ".join(SUPPORTED_BACKGROUNDS))
            Gimp.message(_ascii_safe(msg))
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, _make_glib_error(msg))

        if api_key != api_key_raw and api_key_raw:
            _save_key(api_key)
            _log("normalized api_key (stripped 'Bearer ' prefix) and saved")
        else:
            _save_key(api_key)

        if not _image_alive(image):
            msg = ("The image this plug-in was started with is no longer "
                   "open. Keep the image open while the edit runs.")
            _log("image invalid at run() start")
            Gimp.message(_ascii_safe(msg))
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, _make_glib_error(msg))

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

            _log("using flare: aspect_ratio={!r} resolution={!r} "
                 "background={!r} for selection {}x{}".format(
                     aspect_ratio, resolution, background,
                     x2 - x1, y2 - y1))

            Gimp.progress_init("kie.ai: exporting selection...")
            tmp_path, x1, y1, w, h = _export_selection_to_png(image, bounds)
            _log("exported PNG: " + tmp_path)

            Gimp.progress_init("kie.ai: uploading image...")
            image_url = upload_png_base64(tmp_path, api_key)
            _log("uploaded: " + image_url)

            Gimp.progress_init("kie.ai: submitting edit...")
            task_id = submit_image_edit(
                api_key, image_url, prompt, aspect_ratio,
                resolution=resolution, background=background)
            _log("task_id=" + str(task_id))

            Gimp.progress_init("kie.ai: generating (flare)...")
            result = poll_task(api_key, task_id)
            urls = result.get("resultUrls") or []
            _log("resultUrls count={}".format(len(urls)))
            if not urls:
                raise RuntimeError("kie.ai returned no resultUrls")

            Gimp.progress_init("kie.ai: downloading result...")
            # Always write to a .png extension for GIMP's file_load detection;
            # the actual bytes returned may be PNG (transparent bg) or JPG
            # (opaque bg), but GIMP's loader sniffs the magic bytes, not
            # the extension.
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
                Gimp.message(_ascii_safe(
                    "[OK] kie.ai GPT Image 2.5 Flare edit complete."))
            else:
                _log("image was closed during generation; "
                     "opening result in a new window instead")
                shown = _open_in_new_window(result_path)
                if shown:
                    Gimp.message(_ascii_safe(
                        "[OK] kie.ai GPT Image 2.5 Flare edit complete, "
                        "but the image was closed during generation - result "
                        "opened in a new window."))
                    _log("DONE (new window fallback)")
                else:
                    Gimp.message(_ascii_safe(
                        "[OK] Generated, but image closed and no display "
                        "could be opened. Image saved at: " + result_path))
                    result_path = None  # keep the file for the user
        except (URLError, HTTPError, KeyError, RuntimeError, TimeoutError,
                GLib.Error) as e:
            _log("FAILED: " + repr(e))
            err_text = _ascii_safe(str(e) or repr(e))
            msg = "[ERROR] kie.ai GPT Image 2.5 Flare edit failed: " + err_text
            _log("user-facing error: " + msg)
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, _make_glib_error(msg))
        except Exception as e:
            _log("UNEXPECTED FAILURE:\n" + traceback.format_exc())
            err_text = _ascii_safe(repr(e))
            msg = "[ERROR] kie.ai GPT Image 2.5 Flare edit failed (unexpected): " + err_text
            _log("user-facing error: " + msg)
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, _make_glib_error(msg))
        finally:
            for p in (tmp_path, result_path):
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


Gimp.main(KieImageEdit.__gtype__, sys.argv)
