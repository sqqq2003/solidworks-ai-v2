"""Typed-document cast and annotation reads for native drawing creation.

Session ownership, CloseDoc, and ExitApp stay in ``sw_session`` /
``sw_owned_launch``.
"""

from .typelib import ensure_solidworks_typelib, typelib_major
from .dispatch import as_interface, com_read, unwrap
