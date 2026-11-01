"""Pass a COM null interface pointer to SOLIDWORKS selection methods."""
def select_by_id(extension,name,kind,*,append=False,mark=0):
    import pythoncom
    # SelectByID2's Callout is an IDispatch pointer. ``VARIANT(VT_DISPATCH,
    # None)`` is rejected by some pywin32/SW wrapper combinations while
    # converting None to an interface. Pywin32's Nothing sentinel marshals as
    # a null COM interface pointer, matching VBA's Nothing. Do not retry writes.
    callout=pythoncom.Nothing
    try:
        return extension.SelectByID2(name,kind,0.0,0.0,0.0,bool(append),int(mark),callout,0)
    except Exception as exc:
        raise RuntimeError('SelectByID2 failed for '+kind+' '+name+' (typed null Callout): '+str(exc)) from exc
