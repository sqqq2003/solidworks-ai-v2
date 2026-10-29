"""Completion details must retain later engineering warnings without Tk."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from five_sheet_ui import completion_message


class CompletionMessageTests(unittest.TestCase):
    def test_dimension_warning_after_other_issues_is_visible(self):
        issues=['标题字段未填','PDF文字未验','材料未确认','总图：3处尺寸覆盖']
        text=completion_message({'issues':issues})
        for issue in issues:self.assertIn(issue,text)
        self.assertIn('待工程复核',text)

    def test_large_issue_list_reports_omitted_count(self):
        text=completion_message({'issues':['待核对']*103})
        self.assertIn('另有3项',text)
        self.assertIn('任务记录',text)


if __name__=='__main__':unittest.main()
