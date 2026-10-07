#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# GIMP 3 plug-in: Generate New Image with kie.ai (Grok Imagine Image 2.0)
#
# Result opens in a NEW image window (same UX as the old Gemini script) —
# no dependence on any image being open when the plug-in runs.
#
# Every step is logged to ~/.gimp_kie_debug.log.
#
# Install: copy into
#   C:\Users\Asus\AppData\Roaming\GIMP\3.2\plug-ins\kie_text_to_image\kie_text_to_image.py
# then FULLY quit GIMP (check Task Manager for gimp*.exe) and reopen.

import json
import os
import ssl
import sys
import tempfile
import time
import traceback
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GObject, GLib

KIE_MODEL = "grok-imagine-image-2-0/text-to-image"
JOBS_BASE = "https://api.kie.ai/api/v1"
KEY_FILE  = os.path.expanduser("~/.kie_api_key")
LOG_FILE  = os.path.expanduser("~/.gimp_kie_debug.log")


def _log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[{}] {}\n".format(time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


_log("module kie_text_to_image loaded (pid={})".format(os.getpid()))

if hasattr(ssl, "_create_unverified_context"):
    ssl._create_default_https_context = ssl._create_unverified_context


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


def submit_text_to_image(api_key, prompt, aspect_ratio):
    payload = {
        "model": KIE_MODEL,
        "input": {"prompt": prompt, "aspect_ratio": aspect_ratio},
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


def _open_in_new_window(png_path):
    """Load png_path as a new image and give it a display.
    Returns True if displayed, False if the file could not be shown
    (the caller should then keep the file)."""
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


class KieTextToImage(Gimp.PlugIn):

    def do_query_procedures(self):
        _log("do_query_procedures called")
        return ["kie-text-to-image"]

    def do_set_i18n(self, name):
        return False

    def do_create_procedure(self, name):
        _log("do_create_procedure called for " + str(name))
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*")
        try:
            mask = (Gimp.ProcedureSensitivityMask.DRAWABLE |
                    Gimp.ProcedureSensitivityMask.NO_DRAWABLES |
                    Gimp.ProcedureSensitivityMask.NO_IMAGE)
        except AttributeError:
            mask = (Gimp.ProcedureSensitivityMask.DRAWABLE |
                    Gimp.ProcedureSensitivityMask.NO_DRAWABLES)
        procedure.set_sensitivity_mask(mask)

        procedure.set_menu_label("Generate New Image with kie.ai (Grok)...")
        procedure.add_menu_path('<Image>/Filters/AI Tools/')

        procedure.set_documentation(
            "Generate a new image with kie.ai Grok Imagine text-to-image.",
            "Dialog for prompt, aspect ratio and API key. The result opens "
            "in a new image window. Works with or without an image open.",
            name,
        )
        procedure.set_attribution("Kie GIMP Plugin", "Kie GIMP Plugin", "2026")

        procedure.add_string_argument(
            "prompt", "Prompt", "Describe the image to generate",
            "a serene mountain landscape at sunset",
            GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "aspect_ratio", "Aspect ratio",
            "Output aspect ratio: 1:1, 16:9, 9:16, 4:3, 3:4",
            "1:1", GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "api_key", "API key",
            "kie.ai API key. Saved to ~/.kie_api_key after first run.",
            _read_key(),
            GObject.ParamFlags.READWRITE,
        )
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        _log("run() entered, run_mode={!r}".format(run_mode))

        try:
            if run_mode == Gimp.RunMode.INTERACTIVE:
                _log("INTERACTIVE: importing GimpUi...")
                gi.require_version('GimpUi', '3.0')
                from gi.repository import GimpUi
                _log("GimpUi imported, calling GimpUi.init...")
                GimpUi.init("kie_text_to_image")

                _log("creating ProcedureDialog...")
                dialog = GimpUi.ProcedureDialog.new(
                    procedure, config, "Generate New Image with kie.ai (Grok)")
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
        except Exception:
            _log("DIALOG FAILED with exception:\n" + traceback.format_exc())

        prompt       = (config.get_property("prompt") or "").strip()
        aspect_ratio = (config.get_property("aspect_ratio") or "").strip() or "1:1"
        api_key      = (config.get_property("api_key") or "").strip()

        _log("prompt={!r} aspect_ratio={!r} api_key={}".format(
            prompt, aspect_ratio, "(set)" if api_key else "(empty)"))

        if not api_key:
            api_key = _read_key()
        if not api_key:
            msg = ("No API key. Paste your kie.ai key into the 'API key' "
                   "field of the dialog and press OK.")
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(msg))

        if not prompt:
            msg = "Prompt is empty. Describe the image you want."
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(msg))

        _save_key(api_key)

        result_path = None
        shown = False
        try:
            Gimp.progress_init("kie.ai: submitting prompt...")
            _log("submitting task...")
            task_id = submit_text_to_image(api_key, prompt, aspect_ratio)
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
                "gimp_kie_t2i_{}.png".format(os.getpid()))
            download_to(urls[0], result_path)
            _log("downloaded to " + result_path)

            _log("opening result in a new image window...")
            shown = _open_in_new_window(result_path)

            if shown:
                _log("DONE (opened in new window)")
                Gimp.message("✅ kie.ai text-to-image complete "
                             "(opened in a new window).")
            else:
                Gimp.message(
                    "✅ Generated, but could not open a display. "
                    "Image saved at: " + result_path)
        except (URLError, HTTPError, KeyError, RuntimeError, TimeoutError,
                GLib.Error) as e:
            _log("FAILED: " + repr(e))
            msg = "❌ kie.ai text-to-image failed: " + str(e)
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(msg))
        except Exception as e:
            _log("UNEXPECTED FAILURE:\n" + traceback.format_exc())
            msg = "❌ kie.ai text-to-image failed (unexpected): " + repr(e)
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(msg))
        finally:
            if result_path and shown:
                try:
                    os.unlink(result_path)
                except OSError:
                    pass

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


Gimp.main(KieTextToImage.__gtype__, sys.argv)
