import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import ezdxf
import sw_tool_cli
from solidworks_generator import GenerationResult
from cad_analyzer import primitive_bounds

class SheetResizeIntegrationTests(unittest.TestCase):
    def test_preserve_circle_diameter_moves_center_and_binds_confirmation(self):
        from cad_analyzer import analyze_cad_file
        from profile_edit import resize_profile_dimensions
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'part.dxf';doc=ezdxf.new();doc.units=4;m=doc.modelspace()
            m.add_lwpolyline([(0,0),(100,0),(100,50),(0,50)],close=True);m.add_circle((30,25),5);doc.saveas(path)
            analysis=analyze_cad_file(path);result=resize_profile_dimensions(analysis,0,width_mm=120,height_mm=60,preserve_circle_holes=True)
            self.assertAlmostEqual(result.profiles[1].circle_radius,5)
            self.assertAlmostEqual(result.profiles[1].circle_center[0],26)
            self.assertAlmostEqual(result.profiles[1].circle_center[1],25)

    def test_preserve_circle_rejects_slots(self):
        from cad_analyzer import analyze_cad_file
        from profile_edit import resize_profile_dimensions
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'part.dxf';doc=ezdxf.new();doc.units=4;m=doc.modelspace()
            m.add_lwpolyline([(0,0),(100,0),(100,50),(0,50)],close=True)
            # 矩形槽（四边直线，非长圆孔）仍不支持保持规格。
            m.add_lwpolyline([(20,10),(40,10),(40,20),(20,20)],close=True);doc.saveas(path)
            with self.assertRaisesRegex(ValueError,'独立圆孔和长圆孔'):
                resize_profile_dimensions(analyze_cad_file(path),0,width_mm=120,height_mm=60,preserve_circle_holes=True)

    def test_preserve_obround_slot_keeps_size_and_moves_center(self):
        # 长圆孔（两条直边 + 两端半圆弧）保持规格：尺寸不变，只移动槽心。
        from cad_analyzer import analyze_cad_file
        from profile_edit import resize_profile_dimensions
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'part.dxf';doc=ezdxf.new();doc.units=4;m=doc.modelspace()
            m.add_lwpolyline([(0,0),(200,0),(200,100),(0,100)],close=True)
            # 水平长圆槽：中心(80,50)，槽宽20（高20），槽长40（宽40）。
            m.add_line((60,40),(100,40))
            m.add_line((100,60),(60,60))
            m.add_arc((60,50),10,90,270)
            m.add_arc((100,50),10,270,90)
            doc.saveas(path)
            analysis=analyze_cad_file(path)
            # 找外轮廓（最大闭合轮廓）。
            outer=max(range(len(analysis.profiles)),
                      key=lambda i: primitive_bounds(analysis.profiles[i])[2]-primitive_bounds(analysis.profiles[i])[0])
            result=resize_profile_dimensions(analysis,outer,width_mm=300,height_mm=150,preserve_circle_holes=True)
            # 外轮廓放大到 300×150。
            rb=primitive_bounds(result.profiles[outer])
            self.assertAlmostEqual(rb[2]-rb[0],300)
            self.assertAlmostEqual(rb[3]-rb[1],150)
            # 长圆槽尺寸保持不变（槽长 60、槽宽 20）。
            slot=next(p for i,p in enumerate(result.profiles)
                      if i!=outer and p.closed and p.kind=='LINE_LOOP')
            sb=primitive_bounds(slot)
            self.assertAlmostEqual(sb[2]-sb[0],60)
            self.assertAlmostEqual(sb[3]-sb[1],20)

    def test_preserve_rejects_obround_on_bent_part(self):
        # 带折弯线的零件保持孔径仍阻断（折弯件待后续扩展）。
        from cad_analyzer import analyze_cad_file
        from profile_edit import resize_profile_dimensions
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'part.dxf';doc=ezdxf.new();doc.units=4;m=doc.modelspace()
            m.add_lwpolyline([(0,0),(100,0),(100,50),(0,50)],close=True)
            m.add_circle((30,25),5)
            # 一条红色折弯线（color=1）。
            m.add_line((10,25),(90,25),dxfattribs={'color':1})
            doc.saveas(path)
            analysis=analyze_cad_file(path)
            with self.assertRaisesRegex(ValueError,'带折弯线'):
                resize_profile_dimensions(analysis,0,width_mm=120,height_mm=60,preserve_circle_holes=True)

    def test_generate_uses_resized_profile_and_hole_without_cad_import(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'part.dxf';d=ezdxf.new();d.units=4;m=d.modelspace()
            m.add_lwpolyline([(0,0),(60,0),(60,35),(0,35)],close=True);m.add_circle((30,17.5),9.5);d.saveas(path)
            args=sw_tool_cli.build_parser().parse_args(['--mode','sheet','--input',str(path),'--out','new.SLDPRT',
                 '--profile','1','--thickness','4','--radius','1','--angle','90','--k-factor','0.4','--uniform-scale','1.1'])
            fake=GenerationResult(Path('new.SLDPRT'),0,0,1,(0,)*6,(0,)*6,bend_allowance_verified=True,k_factor_readback=.4)
            with patch('sw_tool_cli.generate_sheet_metal_with_relief_retries',return_value=fake) as generate, patch('sw_tool_cli.emit'):
                self.assertEqual(sw_tool_cli.run_sheet(args),0)
            analysis=generate.call_args.args[0];bounds=primitive_bounds(analysis.profiles[0])
            self.assertAlmostEqual(bounds[2]-bounds[0],66);self.assertAlmostEqual(bounds[3]-bounds[1],38.5)
            self.assertAlmostEqual(analysis.profiles[1].circle_radius,10.45)
            self.assertIs(generate.call_args.kwargs['cad_import'],False)

    def test_single_part_target_length_is_wired_to_geometry_and_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'part.dxf'; d=ezdxf.new(); d.units=4
            d.modelspace().add_lwpolyline([(0,0),(100,0),(100,50),(0,50)],close=True); d.saveas(path)
            args=sw_tool_cli.build_parser().parse_args(['--mode','sheet','--input',str(path),'--out','new.SLDPRT',
                '--profile','1','--target-length','120'])
            fake=GenerationResult(Path('new.SLDPRT'),0,0,1,(0,)*6,(0,)*6)
            with patch('sw_tool_cli.generate_sheet_metal_with_relief_retries',return_value=fake) as generate, patch('sw_tool_cli.emit'):
                sw_tool_cli.run_sheet(args)
            bounds=primitive_bounds(generate.call_args.args[0].profiles[0])
            self.assertAlmostEqual(bounds[2]-bounds[0],120)
            self.assertAlmostEqual(bounds[3]-bounds[1],50)
            self.assertIs(generate.call_args.kwargs['cad_import'],False)
            args.uniform_scale=1.2
            with self.assertRaisesRegex(ValueError,'不能同时使用'):
                sw_tool_cli.run_sheet(args)

    def test_job_binds_scale_to_confirmation(self):
        from desktop_jobs import build_desktop_job
        from project_workbench import build_command
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'part.dxf';source.write_text('x');exe=root/'SLDWORKS.exe';exe.touch()
            v={'kind':'sheet','source':str(source),'output':str(root/'new.SLDPRT'),'sw_exe':str(exe),'profile':'1',
               'thickness':'4','radius':'1','angle':'90','k_factor':'.4','uniform_scale':'1.1'}
            job=build_desktop_job(v,'generate',confirmed=True,preserve_circle_holes=True)
            self.assertIn('--uniform-scale',build_command(job));self.assertIn('--preserve-circle-holes',build_command(job))
            job['uniform_scale']=1.2
            with self.assertRaises(ValueError):build_command(job)

    def test_target_dimensions_are_bound_to_confirmation(self):
        from desktop_jobs import build_desktop_job
        from project_workbench import build_command
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'part.dxf';source.write_text('x');exe=root/'SLDWORKS.exe';exe.touch()
            values={'kind':'sheet','source':str(source),'output':str(root/'new.SLDPRT'),'sw_exe':str(exe),'profile':'1',
                    'thickness':'4','radius':'1','angle':'90','k_factor':'.4','target_length':'120','target_width':'50'}
            job=build_desktop_job(values,'generate',confirmed=True)
            command=build_command(job)
            self.assertEqual(command[command.index('--target-length')+1], '120.0')
            self.assertEqual(command[command.index('--target-width')+1], '50.0')
            job['target_length']=130
            with self.assertRaises(ValueError):build_command(job)
