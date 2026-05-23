import asyncio
import pyautogui
import time

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

INPUT_TOOLS = [
    {
        "name": "mouse_move",
        "description": "Move mouse cursor to absolute screen coordinates.",
        "schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
                "duration": {"type": "number", "description": "Movement duration in seconds. Default 0.2.", "default": 0.2}
            },
            "required": ["x", "y"]
        }
    },
    {
        "name": "mouse_click",
        "description": "Click mouse at current or specified position. Supports left, right, middle buttons and double-click.",
        "schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate (optional, uses current if omitted)"},
                "y": {"type": "integer", "description": "Y coordinate (optional, uses current if omitted)"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                "double": {"type": "boolean", "description": "Double click. Default false.", "default": False},
                "clicks": {"type": "integer", "description": "Number of clicks. Default 1.", "default": 1}
            }
        }
    },
    {
        "name": "mouse_drag",
        "description": "Drag mouse from one position to another.",
        "schema": {
            "type": "object",
            "properties": {
                "from_x": {"type": "integer"},
                "from_y": {"type": "integer"},
                "to_x": {"type": "integer"},
                "to_y": {"type": "integer"},
                "duration": {"type": "number", "default": 0.5},
                "button": {"type": "string", "enum": ["left", "right"], "default": "left"}
            },
            "required": ["from_x", "from_y", "to_x", "to_y"]
        }
    },
    {
        "name": "mouse_scroll",
        "description": "Scroll mouse wheel at current or specified position.",
        "schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate (optional)"},
                "y": {"type": "integer", "description": "Y coordinate (optional)"},
                "clicks": {"type": "integer", "description": "Positive = scroll up, negative = scroll down. Default 3.", "default": 3}
            }
        }
    },
    {
        "name": "get_mouse_position",
        "description": "Get current mouse cursor position.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "keyboard_type",
        "description": "Type text as keyboard input. Supports Unicode.",
        "schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type"},
                "interval": {"type": "number", "description": "Delay between keystrokes in seconds. Default 0.02.", "default": 0.02}
            },
            "required": ["text"]
        }
    },
    {
        "name": "keyboard_hotkey",
        "description": "Press keyboard shortcut combination (e.g. ctrl+c, alt+F4, win+r).",
        "schema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of keys to press simultaneously, e.g. ['ctrl', 'c'] or ['alt', 'F4']"
                }
            },
            "required": ["keys"]
        }
    },
    {
        "name": "keyboard_press",
        "description": "Press a single key or special key (enter, tab, escape, f1-f12, etc.).",
        "schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key name, e.g. 'enter', 'tab', 'escape', 'f5', 'delete', 'backspace'"},
                "presses": {"type": "integer", "description": "Number of times to press. Default 1.", "default": 1}
            },
            "required": ["key"]
        }
    }
]

class InputTools:
    async def _mouse_move(self, args: dict) -> dict:
        pyautogui.moveTo(args["x"], args["y"], duration=args.get("duration", 0.2))
        return {"success": True, "x": args["x"], "y": args["y"]}

    async def _mouse_click(self, args: dict) -> dict:
        x = args.get("x")
        y = args.get("y")
        btn = args.get("button", "left")
        double = args.get("double", False)
        clicks = 2 if double else args.get("clicks", 1)
        if x is not None and y is not None:
            pyautogui.click(x, y, button=btn, clicks=clicks, interval=0.1)
        else:
            pyautogui.click(button=btn, clicks=clicks, interval=0.1)
        return {"success": True}

    async def _mouse_drag(self, args: dict) -> dict:
        pyautogui.moveTo(args["from_x"], args["from_y"], duration=0.2)
        pyautogui.dragTo(args["to_x"], args["to_y"], duration=args.get("duration", 0.5), button=args.get("button", "left"))
        return {"success": True}

    async def _mouse_scroll(self, args: dict) -> dict:
        x = args.get("x")
        y = args.get("y")
        clicks = args.get("clicks", 3)
        if x is not None and y is not None:
            pyautogui.scroll(clicks, x=x, y=y)
        else:
            pyautogui.scroll(clicks)
        return {"success": True, "scrolled": clicks}

    async def _get_mouse_position(self, args: dict) -> dict:
        pos = pyautogui.position()
        return {"x": pos.x, "y": pos.y}

    async def _keyboard_type(self, args: dict) -> dict:
        pyautogui.write(args["text"], interval=args.get("interval", 0.02))
        return {"success": True, "typed": len(args["text"])}

    async def _keyboard_hotkey(self, args: dict) -> dict:
        keys = args["keys"]
        pyautogui.hotkey(*keys)
        return {"success": True, "keys": keys}

    async def _keyboard_press(self, args: dict) -> dict:
        pyautogui.press(args["key"], presses=args.get("presses", 1), interval=0.05)
        return {"success": True, "key": args["key"]}

    def get_handlers(self):
        return {
            "mouse_move": self._mouse_move,
            "mouse_click": self._mouse_click,
            "mouse_drag": self._mouse_drag,
            "mouse_scroll": self._mouse_scroll,
            "get_mouse_position": self._get_mouse_position,
            "keyboard_type": self._keyboard_type,
            "keyboard_hotkey": self._keyboard_hotkey,
            "keyboard_press": self._keyboard_press,
        }
