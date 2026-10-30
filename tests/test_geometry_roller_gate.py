"""Geometry-only roller guesses must never silently become native parts."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import sw_tool_cli
from roller_drawing import RollerDrawingVariant


class GeometryRollerGateTests(unittest.TestCase):
    def test_geometry_candidate_cannot_generate_even_when_defaults_allowed(self):
        candidate=RollerDrawingVariant('无动力滚筒',1,130,40,1.2,30,5,5,None,None,
            '侧视几何识别',frozenset({'overall_length_mm'}),geometry_inferred=True)
        args=sw_tool_cli.build_parser().parse_args(['--mode','roller','--input','plate.dxf',
            '--out','part.SLDPRT','--allow-inferred'])
        with patch('sw_tool_cli.analyze_cad_file',return_value=SimpleNamespace(roller_variants=(candidate,))), \
             patch('sw_tool_cli.generate_roller_part') as generate, patch('sw_tool_cli.emit') as emit:
            self.assertEqual(sw_tool_cli.run_roller(args),1)
            generate.assert_not_called()
            self.assertIn('可能是其他零件',emit.call_args.kwargs['message'])

if __name__=='__main__':unittest.main()
