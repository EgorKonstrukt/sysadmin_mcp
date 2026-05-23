import pyperclip

CLIPBOARD_TOOLS = [
    {
        "name": "clipboard_get",
        "description": "Get current clipboard text content.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "clipboard_set",
        "description": "Set clipboard text content.",
        "schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to copy to clipboard"}
            },
            "required": ["text"]
        }
    }
]

class ClipboardTools:
    async def _get(self, args: dict) -> dict:
        try:
            text = pyperclip.paste()
            return {"content": text, "length": len(text)}
        except Exception as e:
            return {"error": str(e)}

    async def _set(self, args: dict) -> dict:
        try:
            pyperclip.copy(args["text"])
            return {"success": True, "length": len(args["text"])}
        except Exception as e:
            return {"error": str(e)}

    def get_handlers(self):
        return {
            "clipboard_get": self._get,
            "clipboard_set": self._set,
        }
