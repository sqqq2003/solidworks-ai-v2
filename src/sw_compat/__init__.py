"""SolidWorks COM 版本适配层（sw_compat）。

把「pywin32 晚绑定 + SolidWorks 各版本 API 不一致」带来的脆弱 workaround
集中到这里，对外暴露稳定的 Python 函数签名。上层业务代码只调这些稳定函数，
不直接碰原始 COM 对象。

目前收敛了三类 workaround：

* ``com_read``   —— 无参成员既是属性又是方法（不同版本表现不同）。
* ``as_interface`` —— 晚绑定拿到的原始 PyIDispatch 需强转为具体接口，
  否则直接写属性会访问违例（如 ICustomBendAllowance.KFactor）。
* ``typelib``    —— SolidWorks 类型库主版本探测（注册表不可靠，按版本号
  从高到低试加载）。

连接 / 会话状态机（``_connect_task_solidworks`` 等）依赖 ``sw_session`` 的
lease，耦合较深，暂未收敛到这里。
"""

from .typelib import ensure_solidworks_typelib, typelib_major
from .dispatch import as_interface, com_read, unwrap

__all__ = [
    "as_interface",
    "com_read",
    "ensure_solidworks_typelib",
    "typelib_major",
    "unwrap",
]
