import base64
import io
import os
import time
import json
import urllib.request
import urllib.error
from pathlib import Path
from PIL import ImageGrab, Image
import pygetwindow as gw

LMSTUDIO_API_KEY = "lm-studio"
SCREENSHOT_DIR = Path.home() / ".sysadmin_mcp_screenshots"
MAX_SIDE_PX = 1280
JPEG_QUALITY = 85

SCREEN_TOOLS = [
    {
        "name": "screen_capture",
        "description": "Capture the entire screen or a region and save to disk. Returns the file path.",
        "schema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "description": "Optional region: {x, y, width, height}. Omit for full screen.",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"}
                    }
                },
                "scale": {
                    "type": "number",
                    "description": "Scale factor 0.1-1.0. Default 0.5.",
                    "default": 0.5
                }
            }
        }
    },
    {
        "name": "screen_analyze",
        "description": "Capture the screen (or a window) and analyze it using the vision model in LM Studio. Returns the model's description of what it sees.",
        "schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "What to ask about the screen.",
                    "default": "Describe everything you see on this screen in detail."
                },
                "window_title": {
                    "type": "string",
                    "description": "Capture a specific window by title (partial match). Omit for full screen."
                },
                "scale": {
                    "type": "number",
                    "description": "Scale factor 0.1-1.0. Default 0.5.",
                    "default": 0.5
                },
                "model": {
                    "type": "string",
                    "description": "LM Studio model identifier. Omit to use the currently loaded model."
                },
                "lmstudio_url": {
                    "type": "string",
                    "description": "LM Studio API base URL. Default: http://localhost:1234",
                    "default": "http://localhost:1234"
                },
                "use_responses_api": {
                    "type": "boolean",
                    "description": "Use /v1/responses endpoint instead of /v1/chat/completions. Required for LM Studio 0.3.39+. Default: true.",
                    "default": True
                }
            }
        }
    },
    {
        "name": "list_windows",
        "description": "List all visible windows with their titles, positions and sizes.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "capture_window",
        "description": "Capture a specific window by title and save to disk. Returns file path.",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Window title (partial match)"},
                "scale": {"type": "number", "description": "Scale factor 0.1-1.0. Default 0.5.", "default": 0.5}
            },
            "required": ["title"]
        }
    },
    {
        "name": "focus_window",
        "description": "Bring a window to the foreground by title (partial match).",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Window title (partial match)"}
            },
            "required": ["title"]
        }
    }
]


def _resize_for_vlm(img: Image.Image, scale: float) -> Image.Image:
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    if max(img.width, img.height) > MAX_SIDE_PX:
        ratio = MAX_SIDE_PX / max(img.width, img.height)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
    return img


def _to_jpeg_base64(img: Image.Image) -> str:
    rgb = img.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _to_png_base64(img: Image.Image) -> str:
    rgb = img.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class ScreenTools:
    def _save_to_disk(self, img: Image.Image, scale: float) -> tuple[str, int, int]:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        path = SCREENSHOT_DIR / f"screenshot_{ts}.jpg"
        resized = _resize_for_vlm(img, scale)
        resized.convert("RGB").save(str(path), format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return str(path), resized.width, resized.height

    def _grab_screen(self, region: dict | None) -> Image.Image:
        if region:
            bbox = (region["x"], region["y"], region["x"] + region["width"], region["y"] + region["height"])
            return ImageGrab.grab(bbox=bbox, all_screens=True)
        return ImageGrab.grab(all_screens=True)

    def _grab_window(self, title: str) -> tuple[Image.Image, str] | None:
        matches = [w for w in gw.getAllWindows() if title.lower() in w.title.lower() and w.visible]
        if not matches:
            return None
        w = matches[0]
        if w.isMinimized:
            w.restore()
            time.sleep(0.3)
        bbox = (w.left, w.top, w.left + w.width, w.top + w.height)
        return ImageGrab.grab(bbox=bbox, all_screens=True), w.title

    def _call_responses_api(self, b64: str, prompt: str, model: str | None, base_url: str) -> dict:
        url = f"{base_url.rstrip('/')}/v1/responses"
        content = [
            {"type": "input_text", "text": prompt},
            {
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{b64}"
            }
        ]
        payload = {
            "input": [{"role": "user", "content": content}],
            "max_output_tokens": 2048,
            "temperature": 0.1,
            "stream": False
        }
        if model:
            payload["model"] = model
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LMSTUDIO_API_KEY}"
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                text = ""
                for item in result.get("output", []):
                    for part in item.get("content", []):
                        if part.get("type") == "output_text":
                            text += part.get("text", "")
                return {
                    "analysis": text,
                    "model": result.get("model", "unknown"),
                    "endpoint": "responses"
                }
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return {"error": f"HTTP {e.code}: {body}", "endpoint": "responses"}
        except Exception as e:
            return {"error": str(e), "endpoint": "responses"}

    def _call_chat_completions(self, b64: str, prompt: str, model: str | None, base_url: str) -> dict:
        url = f"{base_url.rstrip('/')}/v1/chat/completions"
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                        }
                    ]
                }
            ],
            "max_tokens": 2048,
            "temperature": 0.1,
            "stream": False
        }
        if model:
            payload["model"] = model
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LMSTUDIO_API_KEY}"
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return {
                    "analysis": result["choices"][0]["message"]["content"],
                    "model": result.get("model", "unknown"),
                    "endpoint": "chat/completions"
                }
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return {"error": f"HTTP {e.code}: {body}", "endpoint": "chat/completions"}
        except Exception as e:
            return {"error": str(e), "endpoint": "chat/completions"}

    def _call_lmstudio_vision(self, b64: str, prompt: str, model: str | None, base_url: str, use_responses_api: bool = True) -> dict:
        if use_responses_api:
            result = self._call_responses_api(b64, prompt, model, base_url)
            if "error" in result:
                result["fallback_note"] = "responses API failed, try use_responses_api=false"
            return result
        return self._call_chat_completions(b64, prompt, model, base_url)

    async def _capture(self, args: dict) -> dict:
        region = args.get("region")
        scale = float(args.get("scale", 0.5))
        img = self._grab_screen(region)
        path, w, h = self._save_to_disk(img, scale)
        return {"saved_to": path, "width": w, "height": h}

    async def _analyze(self, args: dict) -> dict:
        prompt = args.get("prompt", "Describe everything you see on this screen in detail.")
        window_title = args.get("window_title")
        scale = float(args.get("scale", 0.5))
        model = args.get("model")
        base_url = args.get("lmstudio_url", "http://localhost:1234")
        use_responses_api = args.get("use_responses_api", True)
        window_name = None
        if window_title:
            result = self._grab_window(window_title)
            if result is None:
                return {"error": f"No window matching '{window_title}'"}
            img, window_name = result
        else:
            img = self._grab_screen(None)
        img = _resize_for_vlm(img, scale)
        b64 = _to_jpeg_base64(img)
        result = self._call_lmstudio_vision(b64, prompt, model, base_url, use_responses_api)
        result["width"] = img.width
        result["height"] = img.height
        if window_name:
            result["window"] = window_name
        return result

    async def _list_windows(self, args: dict) -> dict:
        wins = [
            {
                "title": w.title,
                "left": w.left, "top": w.top,
                "width": w.width, "height": w.height,
                "is_active": w.isActive, "is_minimized": w.isMinimized
            }
            for w in gw.getAllWindows() if w.title and w.visible
        ]
        return {"windows": wins, "count": len(wins)}

    async def _capture_window(self, args: dict) -> dict:
        title = args["title"]
        scale = float(args.get("scale", 0.5))
        result = self._grab_window(title)
        if result is None:
            return {"error": f"No window matching '{title}'"}
        img, window_name = result
        path, w, h = self._save_to_disk(img, scale)
        return {"saved_to": path, "window_title": window_name, "width": w, "height": h}

    async def _focus_window(self, args: dict) -> dict:
        title = args["title"]
        matches = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
        if not matches:
            return {"error": f"No window matching '{title}'"}
        w = matches[0]
        if w.isMinimized:
            w.restore()
        w.activate()
        return {"success": True, "window_title": w.title}

    def get_handlers(self):
        return {
            "screen_capture": self._capture,
            "screen_analyze": self._analyze,
            "list_windows": self._list_windows,
            "capture_window": self._capture_window,
            "focus_window": self._focus_window,
        }