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

LMSTUDIO_API_URL = "http://localhost:1234/v1/chat/completions"
LMSTUDIO_API_KEY = "lm-studio"
SCREENSHOT_DIR = Path.home() / ".sysadmin_mcp_screenshots"

SCREEN_TOOLS = [
    {
        "name": "screen_capture",
        "description": "Capture the entire screen or a region and save to disk. Returns the file path. Use this with fs_read or pass the path to screen_analyze.",
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
        "description": "Capture the screen (or a window) and analyze it using the currently loaded vision model in LM Studio. Returns the model's description of what it sees. Use this to actually SEE and understand screen contents.",
        "schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "What to ask about the screen. Default: 'Describe everything you see on this screen in detail.'",
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

class ScreenTools:
    def _encode(self, img: Image.Image, scale: float) -> tuple[str, int, int]:
        if scale != 1.0:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return b64, img.width, img.height

    def _save_to_disk(self, img: Image.Image, scale: float) -> tuple[str, int, int]:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        path = SCREENSHOT_DIR / f"screenshot_{ts}.png"
        if scale != 1.0:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        img.save(str(path), format="PNG", optimize=True)
        return str(path), img.width, img.height

    def _grab_screen(self, region: dict | None) -> Image.Image:
        if region:
            bbox = (region["x"], region["y"], region["x"] + region["width"], region["y"] + region["height"])
            return ImageGrab.grab(bbox=bbox, all_screens=True)
        return ImageGrab.grab(all_screens=True)

    def _grab_window(self, title: str) -> Image.Image | None:
        matches = [w for w in gw.getAllWindows() if title.lower() in w.title.lower() and w.visible]
        if not matches:
            return None
        w = matches[0]
        if w.isMinimized:
            w.restore()
            time.sleep(0.3)
        bbox = (w.left, w.top, w.left + w.width, w.top + w.height)
        return ImageGrab.grab(bbox=bbox, all_screens=True), w.title

    def _call_lmstudio_vision(self, b64: str, prompt: str, model: str | None, base_url: str) -> dict:
        url = f"{base_url.rstrip('/')}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LMSTUDIO_API_KEY}"
        }
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": b64}
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
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                text = result["choices"][0]["message"]["content"]
                model_used = result.get("model", "unknown")
                return {"analysis": text, "model": model_used}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return {"error": f"HTTP {e.code}: {body}"}
        except Exception as e:
            return {"error": str(e)}

    async def _capture(self, args: dict) -> dict:
        region = args.get("region")
        scale = float(args.get("scale", 0.5))
        img = self._grab_screen(region)
        path, w, h = self._save_to_disk(img, scale)
        return {
            "saved_to": path,
            "width": w,
            "height": h,
            "note": "Screenshot saved to disk. Use screen_analyze to have the vision model describe it, or fs_read to read the raw file."
        }

    async def _analyze(self, args: dict) -> dict:
        prompt = args.get("prompt", "Describe everything you see on this screen in detail.")
        window_title = args.get("window_title")
        scale = float(args.get("scale", 0.5))
        model = args.get("model")
        base_url = args.get("lmstudio_url", "http://localhost:1234")
        window_name = None
        if window_title:
            result = self._grab_window(window_title)
            if result is None:
                return {"error": f"No window matching '{window_title}'"}
            img, window_name = result
        else:
            img = self._grab_screen(None)
        b64, w, h = self._encode(img, scale)
        result = self._call_lmstudio_vision(b64, prompt, model, base_url)
        result["width"] = w
        result["height"] = h
        if window_name:
            result["window"] = window_name
        return result

    async def _list_windows(self, args: dict) -> dict:
        wins = []
        for w in gw.getAllWindows():
            if w.title and w.visible:
                wins.append({
                    "title": w.title,
                    "left": w.left, "top": w.top,
                    "width": w.width, "height": w.height,
                    "is_active": w.isActive, "is_minimized": w.isMinimized
                })
        return {"windows": wins, "count": len(wins)}

    async def _capture_window(self, args: dict) -> dict:
        title = args["title"]
        scale = float(args.get("scale", 0.5))
        result = self._grab_window(title)
        if result is None:
            return {"error": f"No window matching '{title}'"}
        img, window_name = result
        path, w, h = self._save_to_disk(img, scale)
        return {
            "saved_to": path,
            "window_title": window_name,
            "width": w,
            "height": h,
            "note": "Use screen_analyze with window_title to analyze, or fs_read to read raw file."
        }

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