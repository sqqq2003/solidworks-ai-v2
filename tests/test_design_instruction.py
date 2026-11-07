"""Local design-text parsing: explicit values only, never defaults or CAD writes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from design_instruction import describe_design, form_updates, instruction_request, parse_design_text, parse_request


class SheetMetalTextTests(unittest.TestCase):
    def test_reads_all_explicit_sheet_parameters(self):
        design = parse_design_text('板厚 2.5mm 内半径 1 毫米 折弯角度 90° K因子 0.36 第2个轮廓 反向折弯')
        self.assertEqual(design['part_kind'], 'sheet')
        self.assertEqual(design['values'], {'thickness': 2.5, 'radius': 1.0, 'angle': 90.0,
                                            'k_factor': 0.36, 'profile': 2, 'flip': True})
        self.assertEqual(design['pending_confirmation'], [])
        self.assertFalse(design['native_write_allowed'])
        self.assertFalse(design['cad_executed'])

    def test_short_forms_and_full_width_characters(self):
        design = parse_design_text('２．５ｍｍ板厚，Ｒ１，Ｋ０．３６，折弯９０°')
        self.assertEqual(design['values'], {'thickness': 2.5, 'radius': 1.0, 'angle': 90.0, 'k_factor': 0.36})
        design = parse_design_text('t=2.5 R=1 k=0.4 90度折弯')
        self.assertEqual(design['values'], {'thickness': 2.5, 'radius': 1.0, 'k_factor': 0.4, 'angle': 90.0})

    def test_missing_values_stay_empty_and_are_listed(self):
        design = parse_design_text('钣金件 板厚2')
        self.assertEqual(design['values'], {'thickness': 2.0})
        self.assertIn('生成计划前还需填写：内半径、折弯角度、K 因子', design['pending_confirmation'])
        self.assertNotIn('k_factor', design['values'])
        self.assertNotIn('angle', design['values'])

    def test_bare_numbers_are_marked_as_assumed_millimetres(self):
        design = parse_design_text('板厚2.5 R1mm K0.36 折弯角90')
        self.assertEqual(design['unit_assumed_mm'], ['thickness'])
        self.assertEqual(design['unit_assumed_degrees'], ['angle'])
        self.assertIn('板厚：2.5 mm（未写单位，按 mm）', describe_design(design))

    def test_conflicting_values_are_not_chosen(self):
        design = parse_design_text('板厚2.5，厚度3，R1')
        self.assertNotIn('thickness', design['values'])
        self.assertTrue(any('板厚出现了多个不同数值' in item for item in design['pending_confirmation']))

    def test_other_units_are_not_converted(self):
        design = parse_design_text('板厚0.25cm R1 K0.36 折弯90度')
        self.assertNotIn('thickness', design['values'])
        self.assertIn('板厚请使用 mm 填写，未自动换算', design['pending_confirmation'])
        design = parse_design_text('板厚2 R1 K0.36 折弯角度 1.57 rad')
        self.assertNotIn('angle', design['values'])

    def test_out_of_range_values_are_rejected(self):
        design = parse_design_text('钣金 K1.5 板厚2 R1 折弯角90')
        self.assertNotIn('k_factor', design['values'])
        self.assertIn('K 因子需在 0 到 1 之间', design['pending_confirmation'])
        design = parse_design_text('钣金 第0个轮廓 板厚2')
        self.assertNotIn('profile', design['values'])
        design = parse_design_text('钣金 板厚0 R1')
        self.assertIn('板厚必须大于 0', design['pending_confirmation'])

    def test_scale_and_hole_preservation(self):
        design = parse_design_text('钣金等比例缩放到1.5倍，圆孔孔径不变，板厚2 R1 K0.4 角度90')
        self.assertEqual(design['values']['uniform_scale'], 1.5)
        self.assertTrue(design['values']['preserve_circle_holes'])
        design = parse_design_text('钣金 孔径不变 板厚2')
        self.assertNotIn('preserve_circle_holes', design['values'])
        self.assertIn('保持孔径不变需要同时写明缩放倍数', design['pending_confirmation'])
        design = parse_design_text('钣金缩小2倍 板厚2')
        self.assertNotIn('uniform_scale', design['values'])
        self.assertTrue(any('缩小' in item for item in design['pending_confirmation']))


class MachineAndPartTextTests(unittest.TestCase):
    def test_envelope_triple_and_model(self):
        design = parse_design_text('把 QL-5050PX 整机改成 1800×900×1500 mm')
        self.assertEqual(design['part_kind'], 'parametric')
        self.assertEqual(design['values'], {'length': 1800.0, 'width': 900.0, 'height': 1500.0, 'machine': 'QL-5050PX'})
        self.assertEqual(design['pending_confirmation'], [])

    def test_labelled_envelope_ignores_deck_height(self):
        design = parse_design_text('台面高度 800，整机 GT-ZX 长1800 宽900 高1500')
        self.assertEqual(design['values'], {'length': 1800.0, 'width': 900.0, 'height': 1500.0, 'machine': 'GT-ZX'})

    def test_envelope_conflict_and_missing_model(self):
        design = parse_design_text('整机 长1800 宽900 高1500，1900x900x1500')
        self.assertNotIn('length', design['values'])
        self.assertIn('请写明整机型号（QL-5050PX 或 GT-ZX）', design['pending_confirmation'])
        design = parse_design_text('QL-5050PX 和 GT-ZX 都改成 1800x900x1500')
        self.assertNotIn('machine', design['values'])

    def test_roller_line_is_a_machine_not_a_roller_part(self):
        self.assertEqual(parse_design_text('滚筒线 1300x600x750')['part_kind'], 'parametric')

    def test_roller_request_keeps_existing_contract(self):
        text = '把这个滚筒总长度改成800 mm，轴径不变，两端安装结构不变。'
        design = parse_design_text(text)
        self.assertEqual(design['part_kind'], 'roller')
        self.assertEqual(design['values']['target_overall_mm'], 800.0)
        self.assertEqual(design['pending_confirmation'], [])
        self.assertEqual(parse_request(text)['target_overall_mm'], 800.0)
        request = instruction_request({'text': text})
        self.assertEqual(request['parsed']['target_overall_mm'], 800.0)
        self.assertEqual(request['design']['part_kind'], 'roller')
        self.assertFalse(request['native_write_allowed'])

    def test_roller_without_protections_is_pending(self):
        design = parse_design_text('滚筒 规格1 总长900mm')
        self.assertEqual(design['values']['variant'], 1)
        self.assertTrue(any('保持不变的接口' in item for item in design['pending_confirmation']))

    def test_turned_part_variant(self):
        design = parse_design_text('车件 规格2')
        self.assertEqual((design['part_kind'], design['values']), ('turned', {'variant': 2}))

    def test_unknown_or_mixed_requests_fill_nothing(self):
        for text in ('帮我画个东西', '钣金和滚筒一起改'):
            design = parse_design_text(text)
            self.assertIsNone(design['part_kind'])
            self.assertEqual(design['values'], {})
            self.assertTrue(design['pending_confirmation'])
            self.assertIsNone(form_updates(design))

    def test_empty_text_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_design_text('   ')


class FormUpdateTests(unittest.TestCase):
    def test_form_updates_use_desktop_keys_and_strings(self):
        updates = form_updates(parse_design_text('板厚 2.5 R1 K0.36 折弯90度 第2个轮廓 反向折弯'))
        self.assertEqual(updates['fields'], {'kind': 'sheet', 'thickness': '2.5', 'radius': '1',
                                             'angle': '90', 'k_factor': '0.36', 'profile': '2'})
        self.assertEqual(updates['flags'], {'flip': True})
        updates = form_updates(parse_design_text('GT-ZX 1800x900x1500'))
        self.assertEqual(updates['fields'], {'kind': 'parametric', 'length': '1800', 'width': '900',
                                             'height': '1500', 'machine': 'GT-ZX'})

    def test_summary_never_claims_execution(self):
        summary = describe_design(parse_design_text('钣金 板厚2'))
        self.assertIn('未补默认值', summary)
        self.assertIn('未执行模型修改', summary)
        self.assertIn('待确认', summary)


if __name__ == '__main__':
    unittest.main()
