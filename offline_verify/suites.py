"""测试套件注册表：各批已有的离线测试套件。

每个套件一条记录，字段说明：
- id: 套件标识（报告与基线文件共用，不可改名后不改基线）。
- title: 人类可读名。
- kind: "module"（python -m unittest <target>，cwd=检出根）或
  "discover"（python -m unittest discover -s <target>，cwd=检出根/cwd_rel）。
- target: 模块点分路径（kind=module）或 discover 目录（kind=discover）。
- cwd_rel: discover 模式的相对工作目录，module 模式忽略。
- source_pr / source_commit: 该套件计数来源的 PR 与 commit（基线依据）。
- note: 备注（例如“分支未合并，dev 上缺失为预期状态”）。

注册表只描述“怎么跑”，不规定“必须全在”——运行器对缺失套件
只报告、不冒充。新增套件时同步改 baseline.json，不得只改一边。
"""

SUITES = [
    {
        "id": "bridge-contract",
        "title": "桥接契约 (csharp-bridge)",
        "kind": "discover",
        "target": "tests",
        "cwd_rel": "csharp-bridge",
        "source_pr": 26,
        "source_commit": "7363fe49",
        "note": "已合并。C# 侧未编译，契约测试只验 Python 侧 mock。",
    },
    {
        "id": "bridge-wiring",
        "title": "桥接接线 (run_plan S1/S2/S5)",
        "kind": "module",
        "target": "tests.test_bridge_wiring",
        "source_pr": 31,
        "source_commit": "f8b20580",
        "note": "已合并（#31 为 #27 的替代合并）。",
    },
    {
        "id": "bridge-build-reopen",
        "title": "桥接 build/reopen (run_plan S1/S2)",
        "kind": "module",
        "target": "tests.test_bridge_build_reopen",
        "source_pr": 32,
        "source_commit": "e08b8509",
        "note": "Draft PR #32 未合并，dev 上缺失为预期状态。",
    },
    {
        "id": "pipeline",
        "title": "钣金流水线 run_plan",
        "kind": "module",
        "target": "tests.test_sheet_metal_pipeline",
        "source_pr": 23,
        "source_commit": "9d65352a",
        "note": "已合并。",
    },
    {
        "id": "issue19-ckpt",
        "title": "#19 checkpoint / 收尾",
        "kind": "module",
        "target": "tests.test_issue19_ckpt_teardown",
        "source_pr": 23,
        "source_commit": "9d65352a",
        "note": "已合并；#30 的守卫修正另见 recovery-guards。",
    },
    {
        "id": "no-default-k",
        "title": "去默认值 (K/t)",
        "kind": "module",
        "target": "tests.test_no_default_k",
        "source_pr": 29,
        "source_commit": "a7e171cb",
        "note": "已合并。",
    },
    {
        "id": "bend-allowance",
        "title": "折弯 allowance 公式",
        "kind": "module",
        "target": "tests.test_bend_allowance",
        "source_pr": 29,
        "source_commit": "a7e171cb",
        "note": "已合并（#29 的回归项）。",
    },
    {
        "id": "p0-gork",
        "title": "P0 Gork 回归",
        "kind": "module",
        "target": "tests.test_p0_gork_regressions",
        "source_pr": 29,
        "source_commit": "a7e171cb",
        "note": "已合并（#29 的回归项）。",
    },
    {
        "id": "recovery-guards",
        "title": "#30 收尾 / 接管守卫",
        "kind": "module",
        "target": "tests.test_recovery_review_guards",
        "source_pr": 30,
        "source_commit": "d392b74d",
        "note": "已合并。",
    },
    {
        "id": "dxf-extract",
        "title": "模块 ③ DXF 几何提取",
        "kind": "module",
        "target": "tests.test_dxf_extract",
        "source_pr": 35,
        "source_commit": "f9dd625d",
        "note": "Draft PR #35 未合并，dev 上缺失为预期状态。",
    },
    {
        "id": "feature-tree",
        "title": "模块 ④ 特征树执行",
        "kind": "module",
        "target": "feature_tree.tests.test_feature_tree",
        "source_pr": 36,
        "source_commit": "1a8b30fb",
        "note": "Draft PR #36 未合并，dev 上缺失为预期状态。",
    },
    {
        "id": "dependency-engine",
        "title": "模块 ⑤ 整机依赖引擎",
        "kind": "module",
        "target": "dependency_engine.tests.test_dependency_engine",
        "source_pr": 37,
        "source_commit": "0c722db2",
        "note": "Draft PR #37 未合并，dev 上缺失为预期状态。",
    },
    {
        "id": "offline-verify-self",
        "title": "模块 ⑥ 本包自测",
        "kind": "module",
        "target": "offline_verify.tests.test_offline_verify",
        "source_pr": "module-6",
        "source_commit": "this-branch",
        "note": "本批新增；PR 号待创建后由基线文件注记补齐，不改计数。",
    },
]

# 运行器扫描“未注册测试文件”时看的目录（相对检出根）。
# 这些目录里出现 test_*.py 但未被注册时，报告中列为 unregistered，
# 只列出、不运行、不计入通过数。
SCAN_DIRS = [
    "tests",
    "csharp-bridge/tests",
    "feature_tree/tests",
    "dependency_engine/tests",
    "offline_verify/tests",
]


def suite_file_relpath(suite):
    """套件在检出中的相对文件路径（用于存在性检查）。"""
    if suite["kind"] == "module":
        return suite["target"].replace(".", "/") + ".py"
    return suite["cwd_rel"] + "/" + suite["target"]


def suite_command(suite):
    """套件的 unittest 命令（不含解释器与 cwd）。"""
    if suite["kind"] == "module":
        return ["-m", "unittest", suite["target"], "-v"]
    return ["-m", "unittest", "discover", "-s", suite["target"], "-v"]
