"""Property-first COM reads for drawing documents and annotations.

Early-bound SolidWorks wrappers raise ``DISP_E_MEMBERNOTFOUND``
(-2147352573) when a propget is invoked as a method. A live ``InsertNote``
return often does not list ``GetAnnotation`` on its Python class at all.
Skipping those names raised ``AttributeError`` before any COM call. An
undeclared name is still invoked through ``IDispatch`` as a property and as
a method. This module does not rebind a session, CloseDoc, or call ExitApp.
"""

from part_verification import is_member_not_found
from contextlib import contextmanager
from contextvars import ContextVar

_MEMBER_OBSERVER = ContextVar('sw_drawing_member_observer', default=None)


@contextmanager
def observe_member_errors(callback):
    token = _MEMBER_OBSERVER.set(callback)
    try: yield
    finally: _MEMBER_OBSERVER.reset(token)


def record_member_error(name, error):
    callback = _MEMBER_OBSERVER.get()
    if callback is not None and is_member_not_found(error): callback(name, error)

try:
    import pythoncom
    DISPATCH_METHOD = pythoncom.DISPATCH_METHOD
    DISPATCH_PROPERTYGET = pythoncom.DISPATCH_PROPERTYGET
except ImportError:  # Linux tests have no pywin32; these match pythoncom.
    DISPATCH_METHOD = 1
    DISPATCH_PROPERTYGET = 2

# GetIDsOfNames uses this when the name is not on the object.
_DISP_E_UNKNOWNNAME = -2147352570


def _names(name):
    if name.startswith('I') and len(name) > 1 and name[1].isupper():
        return (name,)
    return (name, 'I' + name)


def declared(target, name):
    if getattr(type(target), name, None) is not None:
        return True
    return name in getattr(target, '__dict__', {})


def _invoke(target, attr, args):
    descriptor = getattr(type(target), attr, None)
    if isinstance(descriptor, property):
        got = descriptor.fget(target)
        if args:
            if callable(got) and '_oleobj_' not in getattr(got, '__dict__', {}):
                return got(*args)
            raise TypeError(attr)
        return got
    value = getattr(target, attr)
    if not args:
        if not callable(value):
            return value
        return value()
    if not callable(value):
        raise TypeError(attr)
    return value(*args)


def _oleobj(target):
    bag = getattr(target, '__dict__', None)
    if not isinstance(bag, dict) or '_oleobj_' not in bag:
        return None
    return bag['_oleobj_']


def _missing_name(exc):
    if isinstance(exc, AttributeError):
        return True
    if is_member_not_found(exc):
        return True
    args = getattr(exc, 'args', ())
    if isinstance(args, tuple) and args:
        head = args[0]
        if head in (_DISP_E_UNKNOWNNAME, _DISP_E_UNKNOWNNAME & 0xFFFFFFFF):
            return True
    return False


def _wrap_dispatch(value):
    """Wrap a raw ``PyIDispatch`` so later reads can see ``_oleobj_``."""
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if '_oleobj_' in getattr(value, '__dict__', {}):
        return value
    if not callable(getattr(value, 'Invoke', None)) or not callable(getattr(value, 'GetIDsOfNames', None)):
        return value
    try:
        import win32com.client
    except ImportError:
        return value
    try:
        return win32com.client.Dispatch(value)
    except Exception:
        return value


def _disp_invoke(ole, name, args):
    """Call ``name`` on a live dispatch. Try property and method invoke kinds."""
    try:
        dispid = ole.GetIDsOfNames(name)
    except Exception as exc:
        record_member_error(name, exc)
        if _missing_name(exc):
            raise AttributeError(name) from exc
        raise
    if isinstance(dispid, (tuple, list)):
        if not dispid:
            raise AttributeError(name)
        dispid = dispid[0]
    flags = (DISPATCH_PROPERTYGET, DISPATCH_METHOD) if not args else (DISPATCH_METHOD, DISPATCH_PROPERTYGET)
    last = None
    for flag in flags:
        try:
            result = ole.Invoke(dispid, 0, flag, True, *args)
        except Exception as exc:
            record_member_error(name, exc)
            last = exc
            if is_member_not_found(exc) or _missing_name(exc):
                continue
            raise
        if result is None and not args:
            last = AttributeError(name)
            continue
        return _wrap_dispatch(result)
    if last is not None:
        raise last
    raise AttributeError(name)


def _late_read(target, name, args):
    """Invoke a name the Python class does not declare. Do not skip COM."""
    ole = _oleobj(target)
    if ole is not None and callable(getattr(type(ole), 'GetIDsOfNames', None)) and callable(getattr(type(ole), 'Invoke', None)):
        return _disp_invoke(ole, name, args)
    value = getattr(target, name)
    if not args:
        if not callable(value):
            return value
        return value()
    if not callable(value):
        raise TypeError(name)
    return value(*args)


# Sheet and view chains. On SW2025 these are propgets; calling them is
# DISP_E_MEMBERNOTFOUND. None is the end of the chain, not a missing member.
_VIEW_ITERATORS = frozenset({
    'GetFirstView', 'IGetFirstView',
    'GetNextView', 'IGetNextView',
    'GetFirstAnnotation', 'IGetFirstAnnotation',
    'GetNextAnnotation', 'IGetNextAnnotation',
})


def read_propget(target, name):
    """Read ``name`` with DISPATCH_PROPERTYGET. Do not call a method."""
    descriptor = getattr(type(target), name, None)
    if isinstance(descriptor, property):
        return descriptor.fget(target)
    ole = _oleobj(target)
    if ole is not None and callable(getattr(type(ole), 'GetIDsOfNames', None)) and callable(getattr(type(ole), 'Invoke', None)):
        try:
            dispid = ole.GetIDsOfNames(name)
        except Exception as exc:
            record_member_error(name, exc)
            if _missing_name(exc):
                raise AttributeError(name) from exc
            raise
        if isinstance(dispid, (tuple, list)):
            if not dispid:
                raise AttributeError(name)
            dispid = dispid[0]
        try:
            result = ole.Invoke(dispid, 0, DISPATCH_PROPERTYGET, True)
        except Exception as exc:
            record_member_error(name, exc)
            if is_member_not_found(exc) or _missing_name(exc):
                raise AttributeError(name) from exc
            raise
        return _wrap_dispatch(result)
    value = getattr(target, name)
    if callable(value):
        raise AttributeError(name)
    return value


def view_iterator(name):
    return name in _VIEW_ITERATORS


def read_view_iterator(target, name):
    """Next sheet or view. Property first; a real method is the fallback.

    A successful property read, including None, does not call the method.
    """
    if name not in _VIEW_ITERATORS:
        raise ValueError(name)
    last = None
    for attr in _names(name):
        try:
            return read_propget(target, attr)
        except AttributeError as exc:
            last = exc
            continue
        except Exception as exc:
            record_member_error(name, exc)
            last = exc
            if is_member_not_found(exc) or _missing_name(exc):
                continue
            raise
    for attr in _names(name):
        try:
            value = getattr(target, attr)
        except AttributeError as exc:
            last = exc
            continue
        if not callable(value):
            return value
        try:
            return value()
        except Exception as exc:
            record_member_error(name, exc)
            last = exc
            if is_member_not_found(exc) or _missing_name(exc):
                continue
            raise
    if last is not None and not isinstance(last, AttributeError):
        raise last
    raise AttributeError(name) from last


def read_com_member(target, name, *args):
    """Read ``name`` without calling a property result.

    A declared member uses the Python descriptor. An undeclared member is
    still dispatched. ``DISP_E_MEMBERNOTFOUND`` tries the other invoke kind,
    then the ``I``-prefixed spelling.
    """
    last = None
    for attr in _names(name):
        try:
            if declared(target, attr):
                return _invoke(target, attr, args)
            return _late_read(target, attr, args)
        except AttributeError as exc:
            last = exc
            continue
        except Exception as exc:
            record_member_error(name, exc)
            last = exc
            if is_member_not_found(exc) or _missing_name(exc):
                continue
            raise
    if last is not None and not isinstance(last, AttributeError):
        raise last
    raise AttributeError(name) from last


def read_document_kind(target):
    """``swDocumentTypes_e`` from ``GetType``, or None when the member is absent."""
    if target is None or not any(declared(target, name) for name in _names('GetType')):
        return None
    try:
        value = read_com_member(target, 'GetType')
        return int(value)
    except (TypeError, ValueError):
        return None
    except Exception as exc:
        if is_member_not_found(exc):
            return None
        raise
