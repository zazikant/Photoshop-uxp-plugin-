#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# GIMP 3 plug-in: Generate New Image with kie.ai (Seedream Pro)  [HARDENED]
#
# Result opens in a NEW image window (same UX as the old Gemini script) —
# no dependence on any image being open when the plug-in runs.
#
# Every step is logged to ~/.gimp_kie_debug.log.
#
# Install: copy into
#   C:\Users\Asus\AppData\Roaming\GIMP\3.2\plug-ins\kie_text_to_image\kie_text_to_image.py
# then FULLY quit GIMP (check Task Manager for gimp*.exe) and reopen.
#
# Hardening (vs. naive impl):
#   - ASCII sanitizer: kie.ai responses (e.g. en-dash 'Unauthorized - ...')
#     are translated to pure ASCII so GIMP's latin-1 error display path
#     cannot crash with UnicodeEncodeError and mask the real failure.
#   - _normalize_key: strips surrounding whitespace, surrounding quotes,
#     and a leading 'Bearer ' prefix the user may have pasted along
#     with the actual token.
#   - GLib.Error constructed via new_literal(quark, msg, 0) instead of
#     the positional-string ctor.
#   - Detailed HTTP logging: every request logs method, URL, status,
#     body length; on HTTPError, the response body is captured into
#     the log so the actual kie.ai error payload is visible.

import json
import os
import ssl
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
# seedream pro model identifier (kie.ai createTask sample)
# ---------------------------------------------------------------------------
KIE_MODEL = "seedream/5-pro-text-to-image"

JOBS_BASE = "https://api.kie.ai/api/v1"
KEY_FILE  = os.path.expanduser("~/.kie_api_key")
LOG_FILE  = os.path.expanduser("~/.gimp_kie_debug.log")

# GIMP error display paths use latin-1 in some legacy interop layers,
# which means any non-ASCII char (emoji, en-dash, smart quotes, etc.) in
# an error message throws UnicodeEncodeError and masks the real failure.
# Always sanitize text before it goes into Gimp.message() / GLib.Error().
KIE_ERROR_QUARK = "kie-plugin-error"


def _log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[{}] {}\n".format(time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


_log("module kie_text_to_image (seedream pro) loaded (pid={})".format(os.getpid()))

if hasattr(ssl, "_create_unverified_context"):
    ssl._create_default_https_context = ssl._create_unverified_context


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
    """Build a GLib.Error the correct way (PyGObject's positional
    string ctor is unreliable across versions)."""
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


def submit_text_to_image(api_key, prompt, aspect_ratio,
                         quality="basic", output_format="png",
                         nsfw_checker=False):
    """Submit a seedream/5-pro-text-to-image task.

    Per the kie.ai createTask sample, the input object uses:
      - prompt         (str)
      - aspect_ratio   (str)         <- "1:1", "16:9", "9:16", ...
      - quality        (str)         <- "basic" or "high"
      - output_format  (str)         <- "png", "jpg", "webp"
      - nsfw_checker   (bool)        <- enable NSFW content filter
    No image_input / image_urls field for text-to-image.
    """
    payload = {
        "model": KIE_MODEL,
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "quality": quality,
            "output_format": output_format,
            "nsfw_checker": bool(nsfw_checker),
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


# KIE's published Seedream Pro aspect ratios.
SUPPORTED_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2")

# Seedream Pro quality tiers.
SUPPORTED_QUALITIES = ("basic", "high")

# Seedream Pro supported output formats.
SUPPORTED_OUTPUT_FORMATS = ("png", "jpg", "jpeg", "webp")


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

        procedure.set_menu_label("Generate New Image with kie.ai (Seedream Pro)...")
        procedure.add_menu_path('<Image>/Filters/AI Tools/')

        procedure.set_documentation(
            "Generate a new image with kie.ai Seedream 5 Pro text-to-image.",
            "Dialog for prompt, aspect ratio, quality, output format, "
            "NSFW checker and API key. The result opens in a new image "
            "window. Works with or without an image open.",
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
            "1:1, 16:9, 9:16, 4:3, 3:4, 2:3, 3:2",
            "1:1", GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "quality", "Quality",
            "Image quality tier: basic or high",
            "basic", GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "output_format", "Output format",
            "Output file format: png, jpg, jpeg, or webp",
            "png", GObject.ParamFlags.READWRITE,
        )
        procedure.add_boolean_argument(
            "nsfw_checker", "NSFW checker",
            "Enable NSFW content filter (recommended)",
            False,  # default per kie.ai curl sample for text-to-image
            GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "api_key", "API key",
            "kie.ai API key (no 'Bearer ' prefix). Saved to ~/.kie_api_key after first run.",
            _read_key(),
            GObject.ParamFlags.READWRITE,
        )
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        _log("run() entered (seedream pro t2i), run_mode={!r}".format(run_mode))

        try:
            if run_mode == Gimp.RunMode.INTERACTIVE:
                _log("INTERACTIVE: importing GimpUi...")
                gi.require_version('GimpUi', '3.0')
                from gi.repository import GimpUi
                _log("GimpUi imported, calling GimpUi.init...")
                GimpUi.init("kie_text_to_image")

                _log("creating ProcedureDialog...")
                dialog = GimpUi.ProcedureDialog.new(
                    procedure, config, "Generate New Image with kie.ai (Seedream Pro)")
                try:
                    GimpUi.window_set_transient(dialog)
                except Exception as e:
                    _log("window_set_transient failed (non-fatal): " + repr(e))

                _log("filling dialog with prompt/aspect_ratio/quality/output_format/nsfw_checker/api_key...")
                dialog.fill(["prompt", "aspect_ratio", "quality",
                             "output_format", "nsfw_checker", "api_key"])

                _log("showing dialog (dialog.run())...")
                ok = dialog.run()
                _log("dialog.run() returned {!r}".format(ok))
                dialog.destroy()
                if not ok:
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.CANCEL, None)
        except Exception:
            _log("DIALOG FAILED with exception:\n" + traceback.format_exc())

        prompt        = (config.get_property("prompt") or "").strip()
        aspect_ratio  = (config.get_property("aspect_ratio") or "").strip() or "1:1"
        quality       = (config.get_property("quality") or "").strip() or "basic"
        output_format = (config.get_property("output_format") or "").strip() or "png"
        nsfw_checker  = bool(config.get_property("nsfw_checker"))
        api_key_raw   = (config.get_property("api_key") or "").strip()
        api_key       = _normalize_key(api_key_raw) or _read_key()

        _log("prompt={!r} aspect_ratio={!r} quality={!r} output_format={!r} "
             "nsfw_checker={!r} api_key_len={} (raw_len={})".format(
                 prompt, aspect_ratio, quality, output_format, nsfw_checker,
                 len(api_key), len(api_key_raw)))

        if not api_key:
            msg = ("No API key. Paste your kie.ai key into the 'API key' "
                   "field of the dialog and press OK. (Do NOT include the "
                   "'Bearer ' prefix - the plugin adds it automatically.)")
            Gimp.message(_ascii_safe(msg))
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, _make_glib_error(msg))

        if not prompt:
            msg = "Prompt is empty. Describe the image you want."
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

        quality = quality.lower()
        if quality not in SUPPORTED_QUALITIES:
            msg = ("Unsupported quality. Use: " +
                   ", ".join(SUPPORTED_QUALITIES))
            Gimp.message(_ascii_safe(msg))
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, _make_glib_error(msg))

        output_format = output_format.lower()
        if output_format not in SUPPORTED_OUTPUT_FORMATS:
            msg = ("Unsupported output format. Use: " +
                   ", ".join(SUPPORTED_OUTPUT_FORMATS))
            Gimp.message(_ascii_safe(msg))
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, _make_glib_error(msg))

        # Save the normalized key so future runs skip the 'Bearer ' issue.
        if api_key != api_key_raw and api_key_raw:
            _save_key(api_key)
            _log("normalized api_key (stripped 'Bearer ' prefix) and saved")
        else:
            _save_key(api_key)

        result_path = None
        shown = False
        try:
            Gimp.progress_init("kie.ai: submitting prompt...")
            _log("submitting task (seedream pro t2i)...")
            task_id = submit_text_to_image(
                api_key, prompt, aspect_ratio,
                quality=quality, output_format=output_format,
                nsfw_checker=nsfw_checker)
            _log("task_id=" + str(task_id))

            Gimp.progress_init("kie.ai: generating (seedream pro)...")
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
                Gimp.message(_ascii_safe(
                    "[OK] kie.ai Seedream Pro text-to-image complete "
                    "(opened in a new window)."))
            else:
                Gimp.message(_ascii_safe(
                    "[OK] Generated, but could not open a display. "
                    "Image saved at: " + result_path))
        except (URLError, HTTPError, KeyError, RuntimeError, TimeoutError,
                GLib.Error) as e:
            _log("FAILED: " + repr(e))
            err_text = _ascii_safe(str(e) or repr(e))
            msg = "[ERROR] kie.ai Seedream Pro text-to-image failed: " + err_text
            _log("user-facing error: " + msg)
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, _make_glib_error(msg))
        except Exception as e:
            _log("UNEXPECTED FAILURE:\n" + traceback.format_exc())
            err_text = _ascii_safe(repr(e))
            msg = "[ERROR] kie.ai Seedream Pro text-to-image failed (unexpected): " + err_text
            _log("user-facing error: " + msg)
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, _make_glib_error(msg))
        finally:
            if result_path and shown:
                try:
                    os.unlink(result_path)
                except OSError:
                    pass

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


Gimp.main(KieTextToImage.__gtype__, sys.argv)
