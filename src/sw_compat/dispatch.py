"""晚绑定派发相关的版本适配：属性/方法二义性与类型强转。

SolidWorks 通过 pywin32 暴露的 COM 接口有两个跨版本不一致的坑：

1. 同一个无参成员，在有的版本里是属性、有的版本里是方法
   （如 ``GetTitle`` / ``GetNext``）。直接 ``getattr`` 拿到的东西
   要么是值、要么是 bound method，必须统一判定。

2. 晚绑定（``Dispatch``）拿到的原始对象是通用 ``PyIDispatch``，
   直接写 ``ICustomBendAllowance.KFactor`` 这类属性会访问违例崩溃。
   必须用 ``gencache`` 生成的强类型模块把它 cast 成具体接口。

本模块把这些判定与强转集中起来，让上层调用点不感知这些差异。
"""

from __future__ import annotations

from typing import Any


def unwrap(value: Any) -> Any:
    """把「值」或「返回该值的零参可调用对象」统一成值。

    与 ``com_read`` 同一类问题的更通用形式：有些代码先 ``getattr`` 拿到成员
    （可能是 bound method、也可能是值），再决定是否调用。这里收敛成一句。
    """

    return value() if callable(value) else value


def com_read(instance: Any, name: str) -> Any:
    """读取一个可能是属性、也可能是方法的无参 COM 成员。

    pywin32 对同一无参成员的暴露方式随 SolidWorks 版本变化：
    属性时 ``getattr`` 直接返回值，方法时返回 bound method。
    这里统一「是方法就调用，是属性就用值」。
    """

    return unwrap(getattr(instance, name))


def as_interface(module: Any, instance: Any, interface: str) -> Any:
    """把晚绑定拿到的原始对象强转成 gencache 生成的强类型接口。

    ``module`` 是 ``gencache.EnsureModule`` 返回的强类型模块，
    ``interface`` 是目标接口名（如 ``"ICustomBendAllowance"``）。
    """

    return getattr(module, interface)(instance._oleobj_)
