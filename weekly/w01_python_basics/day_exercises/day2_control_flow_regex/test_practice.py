import unittest
from weekly.w01_python_basics.day_exercises.day2_control_flow_regex.practice import safe_parse_json_from_text

class TestSafeParseJsonFromText(unittest.TestCase):
    
    def test_standard_json_block(self):
        """测试标准的 Markdown JSON 代码块"""
        text = "```json\n{\"name\": \"Alice\", \"age\": 30}\n```"
        expected = {"name": "Alice", "age": 30}
        self.assertEqual(safe_parse_json_from_text(text), expected)

    def test_mixed_text_json(self):
        """测试包含自然语言前缀/后缀的混合文本"""
        text = "Hello! Here is the config:\n```json\n{\"debug\": true, \"port\": 8080}\n```\nLet me know."
        expected = {"debug": True, "port": 8080}
        self.assertEqual(safe_parse_json_from_text(text), expected)

    def test_raw_json_no_block(self):
        """测试没有 Markdown 代码块，但文本本身就是合法 JSON"""
        text = '{"status": "ok", "code": 200}'
        expected = {"status": "ok", "code": 200}
        self.assertEqual(safe_parse_json_from_text(text), expected)

    def test_chinese_symbols_and_spaces(self):
        """测试包含中文标点符号和空格的脏 JSON"""
        text = "```json\n｛\n  “action”： “calc”，\n  “args”： 100\n｝\n```"
        expected = {"action": "calc", "args": 100}
        self.assertEqual(safe_parse_json_from_text(text), expected)

    def test_trailing_comma(self):
        """测试带有尾随逗号的脏 JSON"""
        text = '```json\n{"items": ["apple", "banana",], "status": "active",}\n```'
        expected = {"items": ["apple", "banana"], "status": "active"}
        self.assertEqual(safe_parse_json_from_text(text), expected)

    def test_invalid_json_fallback(self):
        """测试严重损坏的 JSON，确保不崩溃并返回错误字典"""
        text = '```json\n{"name": "Alice", \n```'
        res = safe_parse_json_from_text(text)
        self.assertIn("error", res)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["extracted_text"], '{"name": "Alice",')

    def test_invalid_input_type(self):
        """测试输入为非字符串类型"""
        res = safe_parse_json_from_text(None)  # type: ignore
        self.assertIn("error", res)
        self.assertEqual(res["status"], "failed")


if __name__ == "__main__":
    unittest.main()
