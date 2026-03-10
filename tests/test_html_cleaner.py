from __future__ import annotations

from src.writer.html_cleaner import clean_show_notes


class TestCleanShowNotes:
    def test_basic_html(self):
        html = "<p>这是一段 <b>加粗</b> 文本</p>"
        result = clean_show_notes(html)
        assert "这是一段" in result
        assert "加粗" in result
        assert "<p>" not in result
        assert "<b>" not in result

    def test_links_preserved(self):
        html = '<p>访问 <a href="https://example.com">链接</a></p>'
        result = clean_show_notes(html)
        assert "链接" in result
        assert "https://example.com" in result

    def test_list_conversion(self):
        html = "<ul><li>项目一</li><li>项目二</li></ul>"
        result = clean_show_notes(html)
        assert "项目一" in result
        assert "项目二" in result

    def test_removes_scripts_and_styles(self):
        html = """
        <p>正文内容</p>
        <script>alert('xss')</script>
        <style>.foo { color: red; }</style>
        """
        result = clean_show_notes(html)
        assert "正文内容" in result
        assert "alert" not in result
        assert "color" not in result

    def test_multiple_blank_lines_collapsed(self):
        html = "<p>段落一</p>\n\n\n\n\n<p>段落二</p>"
        result = clean_show_notes(html)
        # 不应有超过 2 个连续空行
        assert "\n\n\n" not in result
        assert "段落一" in result
        assert "段落二" in result

    def test_plain_text_passthrough(self):
        text = "这不是 HTML，就是普通文本"
        result = clean_show_notes(text)
        assert result == text

    def test_empty_input(self):
        assert clean_show_notes("") == ""
        assert clean_show_notes("   ") == ""
        assert clean_show_notes(None) == ""

    def test_complex_show_notes(self):
        html = """
<h2>本期嘉宾</h2>
<p>张三 - AI 研究员</p>
<h2>时间线</h2>
<ul>
  <li>00:00 开场</li>
  <li>05:30 正题</li>
  <li>45:00 总结</li>
</ul>
<p>关注我们：<a href="https://example.com">官网</a></p>
<img src="cover.jpg" alt="封面">
"""
        result = clean_show_notes(html)
        assert "本期嘉宾" in result
        assert "张三" in result
        assert "00:00 开场" in result
        assert "官网" in result
        # img 应被去除
        assert "cover.jpg" not in result

    def test_trailing_spaces_removed(self):
        html = "<p>文本   </p>"
        result = clean_show_notes(html)
        # 每行末尾不应有空格
        for line in result.splitlines():
            assert line == line.rstrip()
