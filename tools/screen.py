import base64
import io
from PIL import ImageGrab, Image
import pygetwindow as gw

SCREEN_TOOLS = [
    {
        "name": "screen_capture",
        "description": "Capture the entire screen or a specific region. Returns base64-encoded PNG image.",
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
                    "description": "Scale factor 0.1-1.0 to reduce image size. Default 0.5.",
                    "default": 0.5
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
        "description": "Capture a specific window by title (partial match). Returns base64 PNG.",
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
    def _img_to_b64(self, img: Image.Image, scale: float = 0.5) -> str:
        if scale != 1.0:
            w = int(img.width * scale)
            h = int(img.height * scale)
            img = img.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode()

    async def _capture(self, args: dict) -> dict:
        region = args.get("region")
        scale = float(args.get("scale", 0.5))
        if region:
            bbox = (region["x"], region["y"], region["x"] + region["width"], region["y"] + region["height"])
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
        else:
            img = ImageGrab.grab(all_screens=True)
        return {"image_base64": self._img_to_b64(img, scale), "width": img.width, "height": img.height}

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
        matches = [w for w in gw.getAllWindows() if title.lower() in w.title.lower() and w.visible]
        if not matches:
            return {"error": f"No window matching '{title}'"}
        w = matches[0]
        if w.isMinimized:
            w.restore()
            import time; time.sleep(0.3)
        bbox = (w.left, w.top, w.left + w.width, w.top + w.height)
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        return {"image_base64": self._img_to_b64(img, scale), "window_title": w.title, "width": w.width, "height": w.height}

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
            "list_windows": self._list_windows,
            "capture_window": self._capture_window,
            "focus_window": self._focus_window,
        }
