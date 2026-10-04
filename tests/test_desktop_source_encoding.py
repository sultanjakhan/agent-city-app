import json
from pathlib import Path
import re
import unittest


class DesktopUnicodeTests(unittest.TestCase):
    def test_all_native_source_strings_have_correct_unicode_without_mojibake(self):
        root=Path(__file__).resolve().parents[1]/"desktop"
        strings=[]
        for name in ("Program.cs","DesktopText.cs"):
            source=(root/name).read_text(encoding="ascii")
            for literal in re.findall(r'"(?:[^"\\]|\\.)*"',source):
                try:text=json.loads(literal)
                except ValueError:continue
                strings.append(text)
                for c in text:
                    if ord(c)>127:
                        self.assertTrue(0x410<=ord(c)<=0x44f or ord(c) in (0x401,0x451,0x2014,0x2026,0xb7,0xab,0xbb),name)
        expected="\u0412\u043e\u0441\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c \u0434\u043e\u0441\u0442\u0443\u043f"
        self.assertIn(expected,strings)
        self.assertIn("\u041e\u0442\u043e\u0437\u0432\u0430\u0442\u044c \u0434\u043e\u0441\u0442\u0443\u043f",strings)


if __name__=="__main__":unittest.main()
