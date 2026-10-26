"""Property-first COM reads for drawing documents and annotations.

Early-bound SolidWorks wrappers raise ``DISP_E_MEMBERNOTFOUND``
(-2147352573) when a propget is invoked as a method. ``read_member`` then
calls the returned object if it is callable, which is the same failure.
This module tries the property, then the method, then the ``I``-prefixed
name. It does not rebind a session, CloseDoc, or call ExitApp.
"""

from part_verification import is_member_not_found


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


def read_com_member(target, name, *args):
    """Read ``name`` without calling a property result.

    ``DISP_E_MEMBERNOTFOUND`` tries the next spelling. Any other exception
    propagates.
    """
    last = None
    for attr in _names(name):
        if not declared(target, attr):
            continue
        try:
            return _invoke(target, attr, args)
        except Exception as exc:
            last = exc
            if is_member_not_found(exc):
                continue
            raise
    if last is not None:
        raise last
    raise AttributeError(name)


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
