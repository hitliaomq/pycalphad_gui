# third_party — 上游官方测试（离线参考）

本目录存放三个上游库**官方源码包（PyPI sdist）自带的测试**，版本与本机安装一致：

| 目录 | 来源 | 版本 |
|---|---|---|
| `pycalphad/` | `pycalphad-0.11.2.tar.gz` 内 `pycalphad/tests/` | 0.11.2 |
| `espei/` | `espei-0.9.1.tar.gz` 内 `tests/` | 0.9.1 |
| `scheil/` | `scheil-0.3.0.tar.gz` 内 `tests/`（含 `alzn_mey.tdb`、`sl_chen.tdb`） | 0.3.0 |

说明：

- 这些测试依赖上游私有 fixture 与完整依赖链（pytest、emcee 等），**默认不参与
  本项目 pytest 收集**（见 `tests/conftest.py` 的 `collect_ignore_glob`）。
- 需要跑上游回归时，在项目根目录执行：
  `pytest tests/third_party/pycalphad`（espei / scheil 同理）。
- pycalphad 测试用的数据库已另外复制一份到 `tests/databases/pycalphad/`，
  供本项目的冒烟测试离线使用（不再依赖 site-packages 路径）。
- 用户日常使用的 13 个热力学库（含 cost507R.TDB）在项目根的 `database/` 文件夹。
