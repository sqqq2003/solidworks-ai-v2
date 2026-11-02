"""Null Callout for SelectByID2, chosen from the pywin32 wrapper.

Qile3 (SolidWorks 2022 rev 30.5, Python 3.14) live probe:

- Early-bound ``win32com.gen_py`` IModelDocExtension accepts Python ``None``.
  ``pythoncom.Nothing`` and ``VARIANT(VT_DISPATCH, None)`` both raise
  "The Python instance can not be converted to a COM object".
- Late-bound ``CDispatch`` accepts ``pythoncom.Nothing`` (and that VARIANT).
  Bare ``None`` is a type mismatch.

Detect gen_py and pass ``None``; otherwise pass ``Nothing``. If that call
fails to marshal, try the other sentinel once. A False return is not retried.
"""
import logging

logger = logging.getLogger(__name__)

CALLOUT_POLICY_NOTE = (
    "SelectByID2 Callout follows the pywin32 wrapper. "
    "Early-bound win32com.gen_py passes Python None; "
    "pythoncom.Nothing and VARIANT(VT_DISPATCH, None) raise "
    "'The Python instance can not be converted to a COM object' on that wrapper. "
    "Late-bound CDispatch passes pythoncom.Nothing; "
    "bare None raises a type mismatch. "
    "The other sentinel is tried once if the first fails to marshal. "
    "A False return is not retried."
)

_DISP_E_TYPEMISMATCH = -2147352571
_accepted = None  # (early_bound, label)


def reset_callout_state_for_tests():
    global _accepted
    _accepted = None


def is_gen_py_early_bound(obj):
    """True for a generated pywin32 wrapper, false for CDispatch / plain objects."""
    module = getattr(type(obj), "__module__", "") or ""
    return "gen_py" in module


def callout_pair(extension):
    """``(first, swap)`` labels. Early-bound is None then Nothing."""
    if is_gen_py_early_bound(extension):
        return ("bare_none", "nothing")
    return ("nothing", "bare_none")


def callout_policy_note(early=None):
    if early is True:
        extra = " This call: early-bound gen_py, try Python None then pythoncom.Nothing once."
    elif early is False:
        extra = " This call: late-bound, try pythoncom.Nothing then Python None once."
    else:
        extra = ""
    return CALLOUT_POLICY_NOTE + extra


def callout_status():
    early, label = _accepted if _accepted else (None, None)
    return {
        "early_bound": early,
        "accepted": label,
        "policy": callout_policy_note(early),
    }


def _materialize_callout(label):
    if label == "bare_none":
        return None
    if label == "nothing":
        import pythoncom
        nothing = getattr(pythoncom, "Nothing", None)
        if nothing is None:
            raise TypeError("pythoncom.Nothing is unavailable")
        return nothing
    raise ValueError("unknown Callout sentinel " + str(label))


def _hresult(exc):
    args = getattr(exc, "args", ())
    if not args or isinstance(args[0], bool) or not isinstance(args[0], int):
        return None
    value = args[0]
    if value > 0x7FFFFFFF:
        value -= 0x100000000
    return value


def _callout_conversion_failure(exc):
    folded = str(exc).casefold()
    if "com object" in folded and "python instance" in folded:
        return True
    if "can not be converted to a com object" in folded or "cannot be converted to a com object" in folded:
        return True
    if "type mismatch" in folded or "typemismatch" in folded or "disp_e_typemismatch" in folded:
        return True
    if "nothing is unavailable" in folded:
        return True
    return _hresult(exc) == _DISP_E_TYPEMISMATCH


def _failure_message(kind, name, tried, early, exc):
    return (
        "SelectByID2 failed for " + str(kind) + " " + str(name)
        + " (callout tried " + ", ".join(tried)
        + "; " + callout_policy_note(early) + "): " + str(exc)
    )


def select_by_id(extension, name, kind, *, append=False, mark=0):
    global _accepted
    early = is_gen_py_early_bound(extension)
    first, swap = callout_pair(extension)
    labels = [first, swap]
    if _accepted and _accepted[0] is early and _accepted[1] in labels:
        labels.remove(_accepted[1])
        labels.insert(0, _accepted[1])
    append_flag = bool(append)
    mark_value = int(mark)
    tried = []
    last = None
    for label in labels:
        try:
            callout = _materialize_callout(label)
            result = extension.SelectByID2(
                name, kind, 0.0, 0.0, 0.0, append_flag, mark_value, callout, 0)
        except Exception as exc:
            last = exc
            tried.append(label)
            # One swap only, and only when the sentinel itself was rejected.
            if _callout_conversion_failure(exc) and len(tried) == 1:
                continue
            raise RuntimeError(_failure_message(kind, name, tried, early, exc)) from exc
        if _accepted != (early, label):
            logger.info("SelectByID2 Callout accepted %s (%s)", label, callout_policy_note(early))
        _accepted = (early, label)
        return result
    raise RuntimeError(_failure_message(kind, name, tried, early, last)) from last
