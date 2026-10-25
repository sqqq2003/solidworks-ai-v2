"""Explicit null IDispatch for typed SW SelectByID2; lazy pywin32 imports."""
def select_by_id(extension,name,kind,*,append=False,mark=0):
    import pythoncom
    from win32com.client import VARIANT
    # Callout is an IDispatch pointer, not VT_EMPTY/VT_NULL. Do not retry writes.
    callout=VARIANT(pythoncom.VT_DISPATCH,None)
    try:
        return extension.SelectByID2(name,kind,0.0,0.0,0.0,bool(append),int(mark),callout,0)
    except Exception as exc:
        raise RuntimeError('SelectByID2 failed for '+kind+' '+name+' (typed null Callout): '+str(exc)) from exc

