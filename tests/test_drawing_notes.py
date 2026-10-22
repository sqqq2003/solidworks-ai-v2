"""drawing_notes：从图纸文字里认板厚 / 材质，且不误判。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import tempfile
import unittest
from pathlib import Path

import ezdxf

from drawing_notes import hints_from_texts, read_drawing_hints


class HintParsingTests(unittest.TestCase):
    def test_reads_thickness_with_keyword(self) -> None:
        hints = hints_from_texts(["钣金件 板厚2.5", "其余"])
        self.assertAlmostEqual(hints.thickness_mm or 0.0, 2.5)
        self.assertEqual(hints.thickness_source, "钣金件 板厚2.5")

    def test_reads_thickness_with_letter_form(self) -> None:
        for text in ("t=1.5", "T 3", "t2.0"):
            with self.subTest(text=text):
                hints = hints_from_texts([text])
                self.assertIsNotNone(hints.thickness_mm)

    def test_ignores_diameters_and_radii(self) -> None:
        hints = hints_from_texts(["Φ8.5 通孔", "R3 圆角", "4-M6-15深"])
        self.assertIsNone(hints.thickness_mm)

    def test_ignores_unreasonable_thickness(self) -> None:
        hints = hints_from_texts(["板厚 200"])
        self.assertIsNone(hints.thickness_mm)
        self.assertTrue(hints.notes)

    def test_first_hit_wins(self) -> None:
        hints = hints_from_texts(["板厚1.2", "厚度3.0"])
        self.assertAlmostEqual(hints.thickness_mm or 0.0, 1.2)

    def test_material_keywords_beat_plain_steel(self) -> None:
        hints = hints_from_texts(["304不锈钢板"])
        self.assertEqual(hints.material, "不锈钢")
        hints = hints_from_texts(["冷轧钢板 SPCC"])
        self.assertEqual(hints.material, "软钢/冷轧")
        hints = hints_from_texts(["铝板 5052"])
        self.assertEqual(hints.material, "铝")

    def test_material_none_when_not_mentioned(self) -> None:
        self.assertIsNone(hints_from_texts(["零件 1"]).material)

    def test_bare_grade_number_is_not_material(self) -> None:
        """标题栏里的「201」是图号，不能当成 201 不锈钢。"""

        self.assertIsNone(hints_from_texts(["201", "304", "316"]).material)
        self.assertEqual(hints_from_texts(["201不锈钢"]).material, "不锈钢")
        self.assertEqual(hints_from_texts(["SUS304"]).material, "不锈钢")

    def test_wall_thickness_is_kept_separate_from_sheet_thickness(self) -> None:
        """滚筒图的「臂厚」是筒身壁厚，不能当成钣金板厚。"""

        hints = hints_from_texts(["201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿"])
        self.assertIsNone(hints.thickness_mm)
        self.assertAlmostEqual(hints.wall_thickness_mm or 0.0, 1.2)
        self.assertEqual(hints.material, "不锈钢")

    def test_escaped_unicode_is_decoded(self) -> None:
        """SolidWorks 导出的文字是 \\U+XXXX 转义，必须先解码再匹配。"""

        escaped = r"201\U+4E0D\U+9508\U+94A2\U+52A8\U+529B\U+6EDA\U+7B52"
        hints = hints_from_texts([escaped])
        self.assertEqual(hints.material, "不锈钢")

    def test_mtext_control_codes_are_stripped(self) -> None:
        hints = hints_from_texts([r"\A1;板厚{\H0.7x;\S2.5^ ;}"])
        self.assertIsNotNone(hints.thickness_mm)

    def test_empty_input(self) -> None:
        hints = hints_from_texts([])
        self.assertIsNone(hints.thickness_mm)
        self.assertIsNone(hints.material)
        self.assertEqual(hints.scanned_texts, 0)


class HintFileTests(unittest.TestCase):
    def _write_dxf(self, directory: Path, texts: list[str], *, in_block: bool = False) -> Path:
        document = ezdxf.new("R2010")
        document.units = ezdxf.units.MM
        if in_block:
            block = document.blocks.new(name="NOTES")
            for index, text in enumerate(texts):
                block.add_text(text, dxfattribs={"height": 2.5}).set_placement(
                    (0, index * 5)
                )
            document.modelspace().add_blockref("NOTES", (0, 0))
        else:
            for index, text in enumerate(texts):
                document.modelspace().add_text(
                    text, dxfattribs={"height": 2.5}
                ).set_placement((0, index * 5))
        target = directory / "hint.dxf"
        document.saveas(target)
        return target

    def test_reads_from_modelspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_dxf(Path(directory), ["板厚 1.5", "201不锈钢"])
            hints = read_drawing_hints(path)
            self.assertAlmostEqual(hints.thickness_mm or 0.0, 1.5)
            self.assertEqual(hints.material, "不锈钢")

    def test_reads_from_block_definition(self) -> None:
        """注记常放在块里，块定义里的文字也要认。"""

        with tempfile.TemporaryDirectory() as directory:
            path = self._write_dxf(Path(directory), ["厚度 3.0"], in_block=True)
            hints = read_drawing_hints(path)
            self.assertAlmostEqual(hints.thickness_mm or 0.0, 3.0)

    def test_non_dxf_returns_empty(self) -> None:
        hints = read_drawing_hints(Path("no_such_file.dwg"))
        self.assertIsNone(hints.thickness_mm)

    def test_broken_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.dxf"
            path.write_text("not a dxf", encoding="utf-8")
            self.assertIsNone(read_drawing_hints(path).thickness_mm)


if __name__ == "__main__":
    unittest.main()


class MaterialThicknessTests(unittest.TestCase):
    """「碳钢板2.0mm」这种材质+数字写法要能读出厚度。"""

    def test_material_thickness_forms(self) -> None:
        from drawing_notes import parse_thickness_value

        cases = {
            "碳钢板2.0mm": 2.0,
            "碳钢板2.5mm": 2.5,
            "碳钢板4mm": 4.0,
            "不锈钢4mm": 4.0,
            "铝板2.5": 2.5,
        }
        for text, want in cases.items():
            parsed = parse_thickness_value(text, allow_bare=True)
            self.assertIsNotNone(parsed, text)
            self.assertAlmostEqual(parsed[0], want, text)


class ZoneBannerTests(unittest.TestCase):
    """分区大字横排在图纸顶部、每列零件各自归到正上方的大字。

    QL-5050 钣金下料图就是这种布局：2.0/2.5/4/5/6mm 五个大字横排，
    同一列从上到下所有行都归该列大字。
    """

    def test_each_column_follows_its_own_banner(self) -> None:
        from drawing_notes import annotate_sheet_parts

        class T:
            def __init__(self, text, x, y, height):
                self.text = text
                self.x = x
                self.y = y
                self.height = height

        banners = [
            T("碳钢板2.0mm", 150.0, 6180.0, 100.0),
            T("碳钢板2.5mm", 2800.0, 6180.0, 100.0),
            T("碳钢板4mm", 4860.0, 6180.0, 100.0),
        ]
        # 两列零件，每列两行：大字在最顶部，第二行离大字比第一行远一倍。
        items = [
            (0, (100.0, 5400.0, 1100.0, 5500.0)),   # 列1 行1
            (1, (100.0, 4800.0, 1100.0, 4900.0)),   # 列1 行2
            (2, (2750.0, 5400.0, 3750.0, 5500.0)),  # 列2 行1
            (3, (2750.0, 4800.0, 3750.0, 4900.0)),  # 列2 行2
        ]
        annotations = annotate_sheet_parts(items, banners)
        self.assertAlmostEqual(annotations[0].thickness_mm, 2.0)
        self.assertAlmostEqual(annotations[1].thickness_mm, 2.0)
        self.assertAlmostEqual(annotations[2].thickness_mm, 2.5)
        self.assertAlmostEqual(annotations[3].thickness_mm, 2.5)


if __name__ == "__main__":
    unittest.main()
