"""Shared conservative checks for sheet-metal execution routes."""

def bend_note_warning(analysis):
    notes=getattr(analysis,'texts',()) or ()
    indicated=any('红' in str(note) and '折弯线' in str(note) for note in notes)
    if indicated and not (getattr(analysis,'bend_lines',()) or ()):
        return '图纸说明红色线为折弯线，但没有识别到折弯线；请核对颜色、图层和轮廓后再生成。'
    return None
