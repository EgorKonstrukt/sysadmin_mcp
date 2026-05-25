import asyncio
import json
import time
import threading
from pathlib import Path
import pyautogui
import pyperclip
from pynput import mouse as pynput_mouse, keyboard as pynput_keyboard

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

MACRO_DIR = Path.home() / ".sysadmin_mcp_macros"

INPUT_TOOLS = [
    {
        "name": "mouse_move",
        "description": "Move mouse cursor to absolute screen coordinates.",
        "schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "duration": {"type": "number", "default": 0.2}
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
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                "double": {"type": "boolean", "default": False},
                "clicks": {"type": "integer", "default": 1}
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
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "clicks": {"type": "integer", "description": "Positive = up, negative = down. Default 3.", "default": 3}
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
                "text": {"type": "string"},
                "interval": {"type": "number", "default": 0.02}
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
                    "description": "Keys to press simultaneously, e.g. ['ctrl', 'c']"
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
                "key": {"type": "string"},
                "presses": {"type": "integer", "default": 1}
            },
            "required": ["key"]
        }
    },
    {
        "name": "macro_record_start",
        "description": "Start recording all mouse and keyboard events into a macro. Returns immediately. Stop with macro_record_stop.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "macro_record_stop",
        "description": "Stop recording and return the captured macro as a list of steps. Optionally save it to disk.",
        "schema": {
            "type": "object",
            "properties": {
                "save_as": {"type": "string", "description": "Filename (without extension) to save the macro to disk. Omit to return steps only."}
            }
        }
    },
    {
        "name": "macro_define",
        "description": "Define a macro manually as a list of steps (without recording). Each step is an action dict. Saves to disk immediately.",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Macro filename (without extension)."},
                "steps": {
                    "type": "array",
                    "description": "List of action steps. Each step: {action, ...params, delay?}. Actions: mouse_move, mouse_click, mouse_drag, mouse_scroll, keyboard_type, keyboard_hotkey, keyboard_press, sleep.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["mouse_move", "mouse_click", "mouse_drag", "mouse_scroll", "keyboard_type", "keyboard_hotkey", "keyboard_press", "sleep"]
                            },
                            "delay": {"type": "number", "description": "Seconds to wait before this step. Default 0."}
                        },
                        "required": ["action"]
                    }
                },
                "description": {"type": "string", "description": "Human-readable description of what this macro does."}
            },
            "required": ["name", "steps"]
        }
    },
    {
        "name": "macro_play",
        "description": "Play back a macro by name (loaded from disk) or from inline steps. Speed multiplier adjusts all delays.",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Macro name to load from disk. Either name or steps is required."},
                "steps": {
                    "type": "array",
                    "description": "Inline steps to run directly without loading from disk.",
                    "items": {"type": "object"}
                },
                "repeat": {"type": "integer", "description": "Number of times to repeat. Default 1.", "default": 1},
                "speed": {"type": "number", "description": "Speed multiplier. 2.0 = twice as fast, 0.5 = half speed. Default 1.0.", "default": 1.0}
            }
        }
    },
    {
        "name": "macro_list",
        "description": "List all saved macros with their descriptions and step counts.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "macro_load",
        "description": "Load a saved macro from disk and return its steps for inspection or editing.",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "macro_delete",
        "description": "Delete a saved macro from disk.",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"]
        }
    }
]


class _Recorder:
    def __init__(self):
        self.steps: list[dict] = []
        self._last_ts: float = 0.0
        self._mouse_listener = None
        self._keyboard_listener = None
        self._lock = threading.Lock()

    def _delay(self) -> float:
        now = time.monotonic()
        d = round(now - self._last_ts, 3) if self._last_ts else 0.0
        self._last_ts = now
        return max(0.0, d)

    def _add(self, step: dict):
        step["delay"] = self._delay()
        with self._lock:
            self.steps.append(step)

    def _on_click(self, x, y, button, pressed):
        if pressed:
            btn = "right" if "right" in str(button) else "middle" if "middle" in str(button) else "left"
            self._add({"action": "mouse_click", "x": x, "y": y, "button": btn})

    def _on_move(self, x, y):
        pass

    def _on_scroll(self, x, y, dx, dy):
        self._add({"action": "mouse_scroll", "x": x, "y": y, "clicks": int(dy * 3)})

    def _on_press(self, key):
        try:
            char = key.char
            if char:
                with self._lock:
                    if self.steps and self.steps[-1].get("action") == "keyboard_type":
                        self.steps[-1]["text"] += char
                        return
                self._add({"action": "keyboard_type", "text": char})
        except AttributeError:
            name = str(key).replace("Key.", "")
            self._add({"action": "keyboard_press", "key": name})

    def start(self):
        self._last_ts = time.monotonic()
        self.steps = []
        self._mouse_listener = pynput_mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll
        )
        self._keyboard_listener = pynput_keyboard.Listener(on_press=self._on_press)
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def stop(self) -> list[dict]:
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()
        return list(self.steps)


def _macro_path(name: str) -> Path:
    MACRO_DIR.mkdir(parents=True, exist_ok=True)
    return MACRO_DIR / f"{name}.json"


def _save_macro(name: str, steps: list[dict], description: str = ""):
    path = _macro_path(name)
    path.write_text(json.dumps({"name": name, "description": description, "steps": steps}, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _load_macro(name: str) -> dict:
    path = _macro_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Macro not found: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _run_step(step: dict, speed: float):
    delay = step.get("delay", 0.0)
    if delay > 0 and speed > 0:
        time.sleep(delay / speed)
    action = step.get("action")
    if action == "mouse_move":
        pyautogui.moveTo(step["x"], step["y"], duration=step.get("duration", 0.2) / speed)
    elif action == "mouse_click":
        x, y = step.get("x"), step.get("y")
        btn = step.get("button", "left")
        clicks = 2 if step.get("double") else step.get("clicks", 1)
        if x is not None and y is not None:
            pyautogui.click(x, y, button=btn, clicks=clicks, interval=0.1)
        else:
            pyautogui.click(button=btn, clicks=clicks, interval=0.1)
    elif action == "mouse_drag":
        pyautogui.moveTo(step["from_x"], step["from_y"], duration=0.2)
        pyautogui.dragTo(step["to_x"], step["to_y"], duration=step.get("duration", 0.5) / speed, button=step.get("button", "left"))
    elif action == "mouse_scroll":
        x, y = step.get("x"), step.get("y")
        if x is not None and y is not None:
            pyautogui.scroll(step.get("clicks", 3), x=x, y=y)
        else:
            pyautogui.scroll(step.get("clicks", 3))
    elif action == "keyboard_type":
        text = step.get("text", "")
        try:
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        except Exception:
            pyautogui.write(text, interval=step.get("interval", 0.02))
    elif action == "keyboard_hotkey":
        pyautogui.hotkey(*step["keys"])
    elif action == "keyboard_press":
        pyautogui.press(step["key"], presses=step.get("presses", 1), interval=0.05)
    elif action == "sleep":
        time.sleep(step.get("seconds", 1.0) / speed)


class InputTools:
    def __init__(self):
        self._recorder: _Recorder | None = None

    async def _mouse_move(self, args: dict) -> dict:
        pyautogui.moveTo(args["x"], args["y"], duration=args.get("duration", 0.2))
        return {"success": True, "x": args["x"], "y": args["y"]}

    async def _mouse_click(self, args: dict) -> dict:
        x, y = args.get("x"), args.get("y")
        btn = args.get("button", "left")
        clicks = 2 if args.get("double") else args.get("clicks", 1)
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
        x, y = args.get("x"), args.get("y")
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
        pyautogui.hotkey(*args["keys"])
        return {"success": True, "keys": args["keys"]}

    async def _keyboard_press(self, args: dict) -> dict:
        pyautogui.press(args["key"], presses=args.get("presses", 1), interval=0.05)
        return {"success": True, "key": args["key"]}

    async def _macro_record_start(self, args: dict) -> dict:
        if self._recorder:
            self._recorder.stop()
        self._recorder = _Recorder()
        self._recorder.start()
        return {"success": True, "status": "recording"}

    async def _macro_record_stop(self, args: dict) -> dict:
        if not self._recorder:
            return {"error": "No recording in progress."}
        steps = self._recorder.stop()
        self._recorder = None
        save_as = args.get("save_as")
        result = {"success": True, "step_count": len(steps), "steps": steps}
        if save_as:
            path = _save_macro(save_as, steps)
            result["saved_to"] = path
        return result

    async def _macro_define(self, args: dict) -> dict:
        name = args["name"]
        steps = args["steps"]
        description = args.get("description", "")
        path = _save_macro(name, steps, description)
        return {"success": True, "name": name, "step_count": len(steps), "saved_to": path}

    async def _macro_play(self, args: dict) -> dict:
        steps = args.get("steps")
        name = args.get("name")
        if not steps and not name:
            return {"error": "Provide either 'name' or 'steps'."}
        if not steps:
            try:
                macro = _load_macro(name)
                steps = macro["steps"]
            except FileNotFoundError as e:
                return {"error": str(e)}
        repeat = args.get("repeat", 1)
        speed = float(args.get("speed", 1.0)) or 1.0
        loop = asyncio.get_event_loop()
        def run():
            for _ in range(repeat):
                for step in steps:
                    _run_step(step, speed)
        try:
            await loop.run_in_executor(None, run)
            return {"success": True, "steps_run": len(steps) * repeat}
        except Exception as e:
            return {"error": str(e)}

    async def _macro_list(self, args: dict) -> dict:
        MACRO_DIR.mkdir(parents=True, exist_ok=True)
        macros = []
        for f in sorted(MACRO_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                macros.append({
                    "name": f.stem,
                    "description": data.get("description", ""),
                    "step_count": len(data.get("steps", [])),
                    "path": str(f)
                })
            except Exception:
                macros.append({"name": f.stem, "error": "Failed to parse"})
        return {"macros": macros, "count": len(macros)}

    async def _macro_load(self, args: dict) -> dict:
        try:
            macro = _load_macro(args["name"])
            return {"success": True, **macro}
        except FileNotFoundError as e:
            return {"error": str(e)}

    async def _macro_delete(self, args: dict) -> dict:
        path = _macro_path(args["name"])
        if not path.exists():
            return {"error": f"Macro not found: {args['name']}"}
        path.unlink()
        return {"success": True, "deleted": args["name"]}

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
            "macro_record_start": self._macro_record_start,
            "macro_record_stop": self._macro_record_stop,
            "macro_define": self._macro_define,
            "macro_play": self._macro_play,
            "macro_list": self._macro_list,
            "macro_load": self._macro_load,
            "macro_delete": self._macro_delete,
        }