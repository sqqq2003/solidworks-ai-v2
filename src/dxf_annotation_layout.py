"""Explicit annotation layout operations; no dimension or production approval."""
import math
from ezdxf import bbox
from ezdxf.entities import get_font_name
from ezdxf.fonts import fonts


def rendered_mtext_extent(entity):
    """Measure the same glyph paths used by the DXF preview renderer."""
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.recorder import Recorder
    recorder=Recorder()
    Frontend(RenderContext(entity.doc),recorder).draw_entities([entity])
    return recorder.player().bbox()


def fit_single_line_mtext(entity, bounds, *, padding, minimum_height, extent_reader=None):
    """Fit one MTEXT into a caller-specified cell, committing only on success.

    Content and style are preserved. Numerical extents depend on installed
    fonts and must still be checked in the target CAD/rendering environment.
    """
    if entity.dxftype() != 'MTEXT':
        raise ValueError('MTEXT required')
    if '\\P' in entity.text or '\n' in entity.text:
        raise ValueError('explicit multiline text requires a multiline layout')
    if len(bounds) != 4 or not all(math.isfinite(v) for v in bounds):
        raise ValueError('finite cell bounds required')
    x0, y0, x1, y1 = bounds
    if not math.isfinite(padding) or padding < 0 or not math.isfinite(minimum_height) or minimum_height <= 0:
        raise ValueError('valid padding and minimum height required')
    width, height = x1-x0-2*padding, y1-y0-2*padding
    if min(width, height) <= 0:
        raise ValueError('cell has no usable area')
    if abs(float(entity.dxf.rotation)) > 1e-8:
        raise ValueError('rotated text requires an explicit rotated layout')
    if not math.isfinite(entity.dxf.char_height) or entity.dxf.char_height < minimum_height:
        raise ValueError('existing text is below the specified minimum height')
    candidate = entity.copy()
    candidate.dxf.attachment_point = 5
    candidate.dxf.flow_direction = 1
    candidate.dxf.insert = ((x0+x1)/2, (y0+y1)/2, entity.dxf.insert.z)
    candidate.dxf.defined_height = 0
    original_height = float(entity.dxf.char_height)
    for _ in range(8):
        font = fonts.make_font(get_font_name(candidate), candidate.dxf.char_height)
        # Use the glyph run width plus font slack, rather than width=0
        # (which some CAD renderers interpret as a narrow wrap column).
        plain = candidate.plain_text()
        conservative = sum(1.4 if ord(c) > 0x2e80 else .5 if c.isspace() else .75
                           for c in plain) * candidate.dxf.char_height
        style_width = float(entity.doc.styles.get(entity.dxf.style).dxf.width) if entity.doc else 1.0
        candidate.dxf.width = max(font.text_width(plain)*1.1, conservative, 1e-6) * max(1.0, style_width) * 1.5
        extent = extent_reader(candidate) if extent_reader else bbox.extents([candidate])
        if not extent.has_data:
            raise ValueError('text extent unavailable')
        scale = min(width/max(extent.size.x, 1e-12), height/max(extent.size.y, 1e-12))
        if scale >= 1-1e-9:
            # Center the actual glyph bounds, including font ascenders.
            candidate.translate((x0+x1-extent.extmin.x-extent.extmax.x)/2,
                                (y0+y1-extent.extmin.y-extent.extmax.y)/2, 0)
            for name in ('attachment_point', 'flow_direction', 'insert', 'width', 'defined_height', 'char_height'):
                setattr(entity.dxf, name, getattr(candidate.dxf, name))
            return {'original_height': original_height, 'height': entity.dxf.char_height,
                    'cell': list(bounds), 'content_changed': False, 'production_approved': False}
        next_height = candidate.dxf.char_height*scale*.98
        if next_height < minimum_height:
            raise ValueError('text cannot fit above the specified minimum height')
        candidate.dxf.char_height = next_height
    raise ValueError('text layout did not converge')
