# pycalphad GUI 架构设计

> 目标：为 `pycalphad 0.11.2` 构建一个类 Thermo-Calc 的桌面 GUI，覆盖
> **数据库读取 → 元素周期表 → 相列表与排除 → 相图/属性绘制 → 图交互 → 高通量 → 导出** 全链路。

---

## 1. 环境实况（已实测，非推测）

| 项 | 实测结论 |
|---|---|
| Python | 3.12.9（系统），`pycalphad 0.11.2` / `matplotlib 3.11.1` / `numpy 2.2.6` / `pandas 2.3.3` / `PyQt6 6.11.0` |
| 绑定后端 | QtAgg 集成冒烟通过（`FigureCanvasQTAgg` + `NavigationToolbar2QT`） |
| 数据库来源 | `pycalphad/tests/databases/`（47 个 `.tdb` + `.dat`，可直接用于自测） |
| `Database` 可 pickle | ✅ 26.6 KB，pickle/loads 均 <10 ms → **进程池并行可行** |
| 线程池共享 `Database` | ✅ 4 任务并发 equilibrium 正常 → 线程池可作为默认并行手段 |
| `equilibrium` 内置并行 | ❌ 源码中无 `multiprocessing` → 并行需自行实现 |

### 1.1 pycalphad API 陷阱清单（血泪，直接约束实现）

这些坑在探针中逐一复现并定位，是 GUI 层必须封装的"脏活"：

| # | 陷阱 | 表现 | 应对 |
|---|---|---|---|
| T1 | `eqplot(x=v.T, ...)` 传反 | `AttributeError: 'TemperatureType' object has no attribute 'species'` | **x 必须是组分**（代码内直接 `x.species.name`），y 可为组分或 T/P。引擎层做轴角色归一化 |
| T2 | `dbf.elements` 含伪元素 | 出现 `'/'−'`（电子气）与 `'VA'`（空位） | 周期表只显示真实元素；计算组分另算，VA 保留为 endmember（见下方 T11） |
| T3 | `binplot` 条件约束 | 报错"必须恰好 1 个变化组分 + 1 个变化势场" | 条件构造器前置校验 |
| T4 | `ternplot` 条件约束 | 报错"必须恰好 2 个变化组分 + 0 个变化势场" | 即**等温等压三元全截面**；固定第三组分应改用等成分截面方案 |
| T5 | `ternplot` 自由度 | `ValueError: Number of degrees of freedom is not zero` | 条件组合错误时给出可读中文提示，而非堆栈 |
| T6 | `calculate(X_ZN=...)` | `AttributeError: variables has no attribute 'X_ZN'` | `calculate` 不接收组分条件；**属性计算统一走 `Workspace`** |
| T7 | `IsoplethStrategy` | `ValueError: need at least one array to concatenate`（0.11.2 上多种组合均失败） | 不纳入主线功能，改为 `ternplot`/`eqplot` 路线满足"截面"需求 |
| T8 | `equilibrium` 耗时 | `binplot` ~12 s、`ternplot` ~15 s | 全部计算异步化 + 可取消 |
| T9 | 结果持久化 | `to_netcdf` 需 `netCDF4`（未安装） | 导出默认 CSV/PNG/SVG/PDF，netCDF 作为可选依赖 |
| T10 | `wks.conditions_dict` | 属不存在 | 正确入口是 `wks.conditions[...]` |

### 1.2 GUI 实现期新增的陷阱（跑起来才暴露）

下面这组是"语法检查全过、一构造控件就崩"的问题，只有把**离屏 GUI 冒烟**跑起来才会暴露。
它们印证了一件事：纯函数的单测覆盖不到 Qt 构造期与 matplotlib 事件层的错误。

| # | 陷阱 | 表现 | 应对 |
|---|---|---|---|
| T11 | 电子气占位 `/-` 没滤干净 | 它被当默认组分送进计算 → `ConditionError: X_/- refers to non-existent component` | 黑名单写成 `VA` / `/-`，并用 `^[A-Za-z][A-Za-z0-9]*$` 兜住 `AL/+` 类电荷物种 |
| T12 | 工作线程里建 Qt 画布 | `UserWarning: Starting a Matplotlib GUI outside of the main thread` | 见 §4.6：后台强制 Agg，Qt 画布只在主线程挂 |
| T13 | matplotlib 没有 `dblclick_event` | `ValueError: 'dblclick_event' is not a valid value for signal` | 双击只能从 `button_press_event` 上读 `event.dblclick` 分辨 |
| T14 | `boxstyle` 传给了 annotate | `AttributeError: 'Annotation' object has no property 'boxstyle'` | `boxstyle` 只存在于 `bbox=dict(...)` 中 |
| T15 | Artist 没有 `set_pickable` | `AttributeError: 'Annotation' object has no attribute 'set_pickable'` | 用 `set_picker(True)` 开启拾取 |
| T16 | 重建下拉框把选择刷没 | 用户选的目标变空，起止值却还留着旧量纲 | `clear()` 前先取回旧目标；空目标显式 `setCurrentIndex(-1)`，别让 Qt 默认选中第 0 项 |
| T17 | 脚本模式下相对导入被拒 | `python app.py` 报 `ImportError: attempted relative import with no known parent package` | 见 §4.7：入口做 `sys.path` 补位 + 绝对导入回退 |
| T18 | 入口文件缺 `__main__` 触发段 | 脚本模式进程启动即退出、窗口根本不出现，且不报任何错 | `app.py` 末尾必须保留 `if __name__ == "__main__": raise SystemExit(main())`；由 `tests/test_entry.py` 锁死 |
| T19 | `__main__.py` 直接跑仍是相对导入 | `python pycalphad_gui/__main__.py` 报 `ImportError: attempted relative import with no known parent package`（T17 只救了 `app.py`） | `__main__.py` 用同一套双模式导入；`tests/test_entry.py` 三条启动路径一起锁 |
| T20 | QSS 写进 f-string 后花括号冲突 | `SyntaxError: f-string: single '}' is not allowed` | QSS 用普通字符串模板 + `__TOKEN__` 占位符替换，绝不嵌进 f-string |
| T21 | PyQt6 `QPen` 形参顺序记反 | `TypeError: QPen(...): argument 4 has unexpected type 'PenJoinStyle'` | 签名是 `(brush, width, style, cap, join)`，**cap 在 join 前** |
| T22 | QPainter 画图坐标混用 int/float | `drawLine(x1,y1,x2,y2)` 只收四个 int，混一个 float 就 `TypeError: arguments did not match any overloaded call` | 图标像素坐标一律 `int()`；sip 抛 TypeError 后进程可能直接 abort，且无 traceback |
| T23 | sip 层异常展开导致进程 abort | 异常在 Qt/sip 回调里抛出后，哪怕 `try/except` 接住，后续 `traceback.print_exc()` 也可能 `Fatal Python error: Aborted`（exit 127/3，无输出） | 先修根因（T21/T22 都是它引出来的）；怀疑"莫名 abort"时用 `-X faulthandler` 逐行打印定位 |
| T24 | 构建顺序：信号连接早于控件创建 | `AttributeError: 'MainWindow' object has no attribute '_act_cancel'` —— `busy_changed` 在工具栏动作创建**之前**就 connect 了 | 构建顺序固定为 `_build_ui → _build_toolbar → _build_menu`；`__init__` 里加注释说明为什么不能调换 |
| T25 | 叠加层触发坐标轴自动缩放 | 画一条 tie line / 标注后整张相图被"悄悄放大"：`ax.plot()` 在 autoscale 开启时 `relim()`，matplotlib 加 5% 边距；且 `_unstale()` 在任何 transform 重算时都会补刀 | `set_figure()` 接管后立即 `ax.set_autoscale_on(False)`；叠加层落笔再套 `_frozen_autoscale()` 双保险 |
| T26 | `binplot` 不认离散数组条件 | `ValueError: need at least one array to concatenate` —— 条件传 `np.array([...])` 必崩，`equilibrium` 却只认数组 | `ConditionPlan.build_ranges()`：等步长扫描还原成 `(start, stop, step)`，`binary_ztpf` 路径专用；其余绘图函数仍用 `build()` |
| T27 | `QPixmap` 需要 QApplication | 无 QApplication 时建 `QPixmap` 进程直接 abort（exit 127，无 traceback），try/except 接不住 | `theme.icon()` 顶部先判 `QApplication.instance() is None`，返回空图标 |
| T28 | `Annotation.contains()` 不可靠 | 合成事件下恒返回 False | 命中判定改用 `get_window_extent()` 的 Bbox + 像素容差 |
| T29 | mpl ≥3.9 `MouseEvent` 没有 `.shift` | AttributeError 或永远 False | 用 `modifiers` frozenset，兼容旧版回落 `.shift` |
| T30 | 隐式命名空间子包 + 顶层 `from pkg.sub import mod` | `ImportError: cannot import name 'theme' from 'pycalphad_gui.ui' (unknown location)` | `ui/` 补 `__init__.py` 变常规包；测试若从别的目录跑，注意别 import 到 site-packages 里的旧副本 |
| T31 | `QMessageBox` 的富文本自动探测 | HTML 标签不在字符串开头时被当纯文本，`<b>`/`<br>` 原样显示（用户实测） | 显式 `msg.setTextFormat(Qt.TextFormat.RichText)`，不要依赖自动探测 |
| T32 | matplotlib 默认 DejaVu Sans 无 CJK 字形 | 标注里的汉字全成"豆腐块" | rcParams 设 `font.sans-serif`（微软雅黑等）+ `axes.unicode_minus=False`；必须在任何 Text 创建**之前**（worker 线程的 Agg Figure 也算），`app.main()` 与 `set_figure()` 双保险 |
| T33 | 手势状态 `_drag_index` 跨手势泄漏 | 拖完标注再拖空白，旧标注被拽着跑 / 框选失效 | `_on_press` 入口与 `_on_release` 拖动分支都显式清零 |
| T34 | `_apply_band_zoom` 用像素阈值比数据坐标 | 成分轴（0~1）上框选缩放永远不生效 | 最小尺寸判定必须先 `transData.transform` 到显示像素再比 |
| T35 | SweepRow 对状态变量禁用起止输入框 | 二元相图要扫温度，温度范围却不可调（用户实测） | 状态变量只换默认值，不禁用；维度约束交给 `ConditionPlan.validate` 报错 |
| T36 | legend 默认固定 | 用户要求图例可拖位置 | `set_figure` 时对每个已有 legend 调 `legend.set_draggable(True)` |
| T37 | `set_figure` 关闭了 autoscale，`reset_view` 却靠 `relim()+autoscale_view()` | 对关闭的轴 `autoscale_view()` 是空操作，且 `relim()` 会把 tie line 算进范围 —— 工具栏"复位视图"点了没反应（用户实测） | `set_figure` 时快照各轴初始范围，`reset_view` 直接恢复快照 |
| T38 | `clear_overlays` 移除 artist 后不重绘 | matplotlib 只改场景不刷帧，屏幕仍是旧画面，"清除标注"看似无效（用户实测） | 清理完毕补一次 `draw_idle()`；`_canvas` 可能尚未挂载，用 `getattr` 守卫 |
| T39 | 拿 `QAbstractButton` 当鼠标事件用 | `buttonClicked` 抛的是按钮不是事件，`QToolButton` **没有** `modifiers()`，点一下元素就 AttributeError（用户实测）；同类的 `checkState()` 在 Qt6 非三态按钮上也没有 | 修饰键用 `QApplication.keyboardModifiers()` 取（键盘触发时更可靠），勾选态用 `isChecked()` |
| T40 | `SYMBOL_TO_Z` 是混合大小写键，调用方却 `.upper()` 去查 | `SYMBOL_TO_Z["FE"]` KeyError 又被 `except KeyError: return` 吞掉 —— Shift 框选整段静默失效，用户只看到"点了没反应" | 按符号**原样**查（见 `elements.get_by_symbol` 先原样、后退大写的两段式）；查不到的符号跳过而不是作废整段 |
| T41 | 高通量结果记录用 pycalphad 的 sympy `Variable` 当键 | conds 的键是 `v.T` / `v.X('V')`，而 `DataFrame(records, columns=['T','V',…])` 用字符串匹配，一个都配不上 —— **整张结果表全 NaN**，列头却看起来正常（用户实测） | `conds.values()` 与轴名 zip 出字符串键，并把 output 名统一翻成中文列头，与 `columns` 同名同序 |
| T42 | 高通量只断言"列存在"，不断言"值" | 上面那条致命 bug 在这套断言下一直显示全绿 | `test_high_throughput_has_real_values_not_nan` 逐格检查数值、扫描轴列必须等于输入采样点 |
| T43 | 属性页扫温度时 conds 里没有任何组分条件 | pycalphad 直接 `ValueError: Number of degrees of freedom is not zero`，属性页"没有出图"（用户实测） | 扫 T 必须钉住一个组分的摩尔分数；扫组分时**只能给这一个组分条件**（多给一个反而触发同样的自由度冲突） |
| T44 | 用 `values.ndim > 1` 判定"逐相曲线" | Workspace 在组分扫描下返回的是 **1D 平衡态数组**，于是同一条曲线被贴到每个相名下，4 条完全相同的线，读图必错 | 先比 `shape[0] == len(扫描点)`，1D 一律当作"平衡态"单条曲线；`np.atleast_1d` 兜住单点扫描的 0 维返回值 |
| T45 | 属性页的固定温度 / 固定组分来自 UI，引擎里却硬编码 | `_fixedT` spinbox 改了不生效，扫温度还缺组分 | `options={'fixed_t', 'fixed_x'}` 显式传入；扫描轴切换时两个输入框互斥可用 |

---

## 2. 分层架构

```
┌──────────────────────────────────────────────────────────────────────┐
│  L5 表现层   ui/                                                      │
│     主窗口 / 元素周期表 / 相列表 / 条件面板 / 三个 Tab / 导出对话框    │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ Qt Signals（单向，UI 不反向依赖下层细节）
┌───────────────────────────▼──────────────────────────────────────────┐
│  L4 异步层   workers/   QRunnable + QThreadPool                       │
│     进度信号 / 取消信号 / 异常信号 / 完成信号                          │
└───────────────────────────┬──────────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────────┐
│  L3 业务层   core/                                                    │
│     DatabaseManager  条件构造器(CondSet)  PlotEngine                  │
│     PropertyEngine   HighThroughputEngine  Exporter  MacroEngine      │
│     ※ 纯 Python，不 import PyQt6 → 可独立单测、可复用为 CLI            │
└───────────────────────────┬──────────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────────┐
│  L2 基础设施  elements.py（118 元素数据） / config.py（常量、配色）   │
└───────────────────────────┬──────────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────────┐
│  L1 pycalphad 0.11.2  Database / equilibrium / eqplot / binplot /    │
│     ternplot / Workspace / IsolatedPhase                              │
└──────────────────────────────────────────────────────────────────────┘
```

**依赖方向严格单向向下。** L3 不感知 Qt，L3↔L4 通过数据类（dataclass）传递，
保证 `tests/test_smoke.py` 可在无 GUI 环境下跑通全流程。

---

## 3. 核心数据模型

```python
@dataclass
class LoadedDatabase:
    name: str            # 文件名
    path: Path
    dbf: Database        # pycalphad Database 实例
    display_elements: list[str]   # 周期表展示（已剔除 '-' / 'VA'）
    all_elements: list[str]       # 计算可选组分
    phases: dict[str, PhaseInfo]  # 名称 → 结构信息
    species: list[str]
    load_time_s: float
    warnings: list[str]

    # 元素符号 → 计算组分的三个口径（T52/T53）：
    #   components_for()    严格版，坏符号抛 CalculationError（仅在该报错时调用）
    #   components_safe()   永不抛异常，(可用组分, 被忽略符号)；UI 联动全走这路
    #   sweep_candidates()  可作扫描轴 / 摩尔分数输入的元素（剔除 VA 与库外符号）
    #   comps_of()          components_safe 的静默版，只要可用组分

@dataclass
class PhaseInfo:
    name: str
    n_sublattices: int
    constituents: list[frozenset]  # 用于材质/说明
    model_type: str                # 从 model_hints 推断

@dataclass
class PlotRequest:      # 一次相图计算的完整描述
    request_id: str
    system: tuple[str, ...]        # 选中元素 + VA
    phases: tuple[str, ...]        # 过滤后的相
    diagram_type: str              # 'binary_ztpf' | 'ternary_isothermal' | 'eqplot'
    conditions: dict               # {v.T: ..., v.X('AL'): ...}
    x_var: Any; y_var: Any
    options: dict                  # tielines/colors/etc.

@dataclass
class HTJob:            # 高通量任务
    job_id: str
    system: tuple[str, ...]
    phases: tuple[str, ...]
    sweep: dict[str, np.ndarray]   # 扫描维度
    outputs: tuple[str, ...]       #  collecting GM / stable phases ...
    parallel: int
```

---

## 4. 关键设计决策

### 4.1 相过滤为什么不在 UI 层做
`phases` 列表是几乎所有 pycalphad 调用的公共入参。若分散在各处过滤，极易出现
"排除的相仍出现在图例里"这类不一致。因此 **过滤收敛到 `PlotRequest.phases`**，
由 UI 的选中态 → `SelectionState` 单一数据源 → 所有引擎只读它。

### 4.2 属性绘制为何走 `Workspace` 而非 `calculate`
实测 T6 表明 `calculate` 无法接收组分条件；而
`Workspace(dbf, comps, phases, conds).get('GM'|'HM'|'SM'|'CPM')` 稳定返回与
条件网格同形的数组。亚稳相线则用 `IsolatedPhase(name, wks.copy())(f'GM({name})')`。
两者统一在 `PropertyEngine` 后返回 `(x_values, {phase: y_values})`。

### 4.3 图的交互能力（Matplotlib 原生缺失的部分）

**不使用 `NavigationToolbar`**。它会与自建交互争抢鼠标事件（"点了标签却触发了平移"），
改为 canvas 独占事件、自建工具集：

| 能力 | 实现方式 | 操作方式 |
|---|---|---|
| 加相标签 | `Axes.annotate` + `bbox`，维护 `self._labels` | 标签模式点击放置，可拖拽 |
| 加 tie line | 两次点击累加端点 → 追加 `Line2D` | 连线模式依次点两点 |
| 删除标注 | 命中测试 `contains(event)` 反向遍历 | 右键点中处 |
| 清理标注 | `clear_overlays()` | 工具栏"清除标注" |
| 缩放 / 平移 | 自建（滚轮以光标为锚、中键按住拖动、选择模式左键拖动） | 滚轮 / 中键 / 左键 |
| 复位视图 | `reset_view()` 还原 xlim/ylim | 双击 或 工具栏按钮 |
| 改坐标范围 | `set_axis_limits()` | 工具栏"复位视图"旁的数据框 |
| 对数轴 | `set_log_scale()`（三元三角投影不支持，调用前需判定） | 工具栏"对数轴" |
| 查看数据 | `motion_notify_event` 回传 `(x, y)` 到状态栏 | 移动鼠标 |

坐标轴**变量的切换不在这一层**：pycalphad 要求 `eqplot` 的 x 必须是组分（T1），
任意换轴很可能直接崩，因此换轴属于"重新构造条件 → 重算"的范畴，由条件面板负责。

### 4.4 高通量并行策略
| 方案 | 优点 | 缺点 | 采用 |
|---|---|---|---|
| 主线程串行 | 简单 | 界面冻结 | 否 |
| QThreadPool（线程） | 取消简单、Database 可共享 | GIL 限制 CPU 密集 | **默认** |
| ProcessPoolExecutor | 真并行（Database 已验证可 pickle） | 取消难、启动开销 | 可选开关 |

默认线程池，保留 `use_process_pool` 开关；两者都通过同一 `ProgressReporter` 上报。

### 4.5 取消与错误处理

- 所有 Worker 继承 `BaseWorker`，带 `is_cancelled` 原子标志；**每个任务单元结束后检查**，
  不依赖抢占式中断（pycalphad 无中断点）。取消在"当前这一批算完"时生效，中途不会硬切。
- 计算异常统一经 `failed` 信号携带**已翻译的中文诊断**（把 T1~T15 的英文错訳映射到
  "原因 + 怎么办"），完整堆栈写入日志，不直接弹给用户。
- 高通量扫描里单点失败记进 `failures`，不静默丢失——批量计算最怕"少算了几个还不知道"。

### 4.6 线程与画布：后台只出图，前台只挂画布

pycalphad 的 `binplot/ternplot/eqplot` 内部调 `plt.subplots()`，而它们跑在 `QRunnable`
工作线程里。若后端是 `QtAgg`，就等于让工作线程去 new 一个 `QWindow` ——
Qt 要求所有 GUI 对象都在主线程创建，Windows 上会间歇性崩溃。

规则：

```
app 启动   matplotlib.use("Agg")          # 全局后端，进程内不再切换
   ↓
工作线程   让 pycalphad 在 Agg 下建 Figure  # 只产出"纯数据 + Agg 画布"
   ↓
主线程     InteractiveCanvas.set_figure()  # FigureCanvasQTAgg(figure)
                                          # 构造时顺带 figure.set_canvas(self)
                                          # → 之后的绘制与交互全在主线程
```

`tests/test_gui_headless.py::test_canvas_attached_on_main_thread` 锁死了这条线：
Agg 后端下 Figure 上不得出现 Qt 画布，`set_figure` 之后必须换成 Qt 画布。

### 4.7 启动入口：脚本模式与包模式并存

需求是"直接运行 `app.py`，再去界面里选数据库"。这对入口文件提出了两个互相冲突的要求，
`app.py` 同时满足它们：

```python
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # 包模式：python -m pycalphad_gui
    from .config import APP_NAME, APP_VERSION, LOG_FORMAT
    from .ui.main_window import MainWindow
except ImportError:  # 脚本模式：python app.py
    from pycalphad_gui.config import APP_NAME, APP_VERSION, LOG_FORMAT
    from pycalphad_gui.ui.main_window import MainWindow
```

三点说明，都是实测结论：

1. **不能只改 `__package__`**。脚本运行时 `__main__.__spec__` 是 `None`，
   importlib 的 `_sanity_check` 会直接拒绝相对导入 —— 实测把 `__package__`
   赋成 `"pycalphad_gui"` 依旧报同样的错，必须换成绝对导入。
2. **`sys.path` 要补的是"包目录的上一级"**。脚本模式下 `sys.path[0]` 是 `app.py`
   所在目录（即包目录），而包在其上一级。
3. **末尾的 `__main__` 触发段不能漏**。少了它，脚本模式会静默地启动即退出
   （无窗口、无报错），很难查 —— 现已由 `tests/test_entry.py` 中的脚本模式用例锁死。

**同一套双模式导入同样适用于 `__main__.py`**（T19）。三点按 T17 复述一遍：

1. 脚本模式下 `__package__` 是 `''` 而不是包名，`__spec__` 是 `None`（实测赋值救不回来），
   所以必须 `try: from .app import main / except ImportError: from pycalphad_gui.app import main`。
2. 补的 `sys.path` 条目是**包目录的上一级**，不是包目录自己。
3. `if __name__ == "__main__": raise SystemExit(main())` 保留在原处 ——
   包模式下 `-m` 执行本文件也会走到这段，脚本模式下则由它触发。

四条启动命令（都是同一个 `main()`）：

| 命令 | cwd | 导入机制 |
|---|---|---|
| `python pycalphad_gui/app.py` | `pycalphad_gui/` | 脚本模式，双模式导入 |
| `python pycalphad_gui/__main__.py` | `pycalphad_gui/` 或更高层 | 脚本模式，双模式导入 |
| `python -m pycalphad_gui` | `pycalphad_gui/` | 包模式，相对导入 |
| `pycalphad-gui` | 任意（装过 `pip install -e .`） | 控制台脚本 → `pycalphad_gui.__main__:main` |

数据库导入统一收敛在 `MainWindow.load_database()`，三条入口（工具栏按钮 / 菜单 /
拖拽文件）都走它，界面状态由它一处切换：

| 状态 | 引导卡 `_empty` | 组分标签 | 三个功能页 |
|---|---|---|---|
| 启动后未载入 | 可见 | 隐藏 | 全部 `setTabEnabled(False)` |
| 载入成功 | 隐藏 | 可见 | 全部启用 |

拖拽路径额外校验扩展名：`.tdb` / `.dat` 走 `load_database()`，图片扩展名
（`.png` / `.jpg` / `.jpeg` / `.bmp` / `.tif` / `.tiff`）走 `load_image()`，
其余一律拒绝并在状态栏说明，避免误把别的文件拖进来。

### 4.8 测试策略：无头跑真控件
纯函数单测覆盖不到 Qt 构造期与 matplotlib 事件层的错误（T11~T18 全是在这一层暴露的）。
因此另有一套**离屏 GUI 冒烟**：`QT_QPA_PLATFORM=offscreen` 下构造真实的 `MainWindow`、
载入数据库、排除相、后台线程真算一张小网格二元图、加标签、导出 PNG。
它不需要显示器，却会把"语法能过、一构造就崩"的问题全部挡在交付之前。

### 4.9 相图数字化：纯算法核心 + 薄 Qt 壳

把一张**已有的相图图片**（截图 / 扫描件 / 文献图）还原成"成分 + 相"的数据表。
核心难点不在 Qt，而在图像处理，因此刻意拆成两层：

```
core/digitizer.py        纯 Python + numpy，不 import PyQt6
    ├─ image_to_array / to_gray / dark_mask      图像 → 墨迹掩膜
    ├─ Calibration                               3 点仿射标定（重心权重）
    ├─ detect_grid_lines / remove_grid_lines     网格线检测与擦除
    ├─ snap_to_boundary / project_to_polygon     边界点吸附
    └─ sample_grid / regions_to_frame / save_digitized_csv
                              ↓
ui/digitize_canvas.py    显示、缩放平移、十字/三线光标、区域回显
ui/digitize_tab.py       五步流程的 UI 编排
```

**为什么标定只用 3 个点就能同时覆盖二元与三元**：二元矩形与三元三角形都是
"3 个角点决定一个仿射/重心映射"的图形。二元用矩形三顶点算仿射变换；
三元直接把三个顶点当作**三个组分的基向量**——此时重心权重 (λ₁, λ₂, λ₃)
**恰好就是三个摩尔分数**，不需要任何额外换算。两种图共用同一套
`Calibration.weights()` / `to_data()` / `to_pixel()` 接口，只是语义不同。

**网格线为什么用"方向投影"而不是霍夫变换**：霍夫要对每个角度建累加器，参数
（θ 分辨率、阈值）对虚线极不鲁棒。这里做的是 Radon 式的定向投影——把暗像素
投到"垂直于候选角度"的轴上分箱，箱内像素数出现尖峰且沿该方向**够长**就是一条
贯通线。判断"够长"用 **max-gap 比值**（最长缺口 / 跨度），所以虚线照样认（T63）。
候选角度是确定的：二元 `(0°, 90°)`，三元 `(0°, 60°, 120°)`，由图的类别直接给出，
不必搜索。

**区域采样**：边界点连成多边形后用 `matplotlib.path.Path.contains_points` 在
多边形内铺规则网格，只保留落在区域里的点，再经 `Calibration.to_data()` 换成
成分。多个区域用 `pandas.concat` **纵向拼接**——下一个区域的点永远追加在
上一个区域的点**下面**，并带 `region` / `phase` 两列区分。

### 4.10 界面双语：一份词典 + 整树遍历，而不是几千处 tr()

需求是"右上角切语言、默认英文、选择记住"。逐字符串包 `tr()` 要动上千处
代码，不可维护，因此采用**运行时整树翻译**：

* `i18n.py` 只持一份 `中文 → 英文` 词典（`i18n_zh_en_ui.py` 界面文案 +
  `i18n_zh_en_core.py` 引擎消息 / 118 元素名），反向表自动生成；
  顶层不 import PyQt6，无界面的测试也能安全导入。
* `tr()` **幂等**（已是目标语言立即返回）——这让"启动扫一遍"与"新建控件
  再翻一次"可以共存，纯数据（相名 / 元素符号 / 数值）零开销直通。
* `apply_to()` 遍历 `findChildren(QWidget)` + `QAction`/`QMenu`，逐类控件
  翻 text / title / placeholder / tooltip / itemText / 表头单元格；
  `apply_to_figure()` 补 matplotlib 的 `Text`（轴题 / 图例 / 刻度）。
* 引擎在后台线程生成的图（轴题"温度 T (K)"、图例"（无有限值）"）在
  `InteractiveCanvas.set_figure()` 挂画布时**就地**翻一遍。
* **显示与数据分离**：表格表头只翻显示，DataFrame / 导出 CSV 仍是原始列名；
  下拉框一律 `addItem(文案, 内部键)` + `currentData()`，翻译永远不会污染
  内部键（`diagram_type()` 一度拿显示文本当 key，切语言就崩）。
* **数据型控件跳过文字翻译**：示例下拉里放的是文件路径，片段翻译会把
  `phase` 改成"相"，而单字不进反向片段表，切回英文只能留下半截路径；
  这类控件打 `i18nSkipText` 属性，`apply_to` 只翻 tooltip，不碰正文。
  宏页的日志 / 命令回显是只读多行文本（大多是运行数据），同样不参与整树
  翻译，改由 `MacroTab.retranslate()` 按**原始中文**重放。
* **短译文不进反向表**：英文值不足 4 个字符不建反向条目（防标点片段自伤），
  所以按钮文案要避免 `Run` 这类三字母译文——宏页用的是 `Run Step`。

词典覆盖由测试锁死：`test_i18n_dictionary_is_complete` 用 AST 扫源码里**每一个**
含汉字的字面量（f-string 按常量片段逐个看），要求译文零汉字残留——只查整串
字面量的扫描会给"f-string 拼接句全部漏网"的假绿。

### 4.11 宏命令：只做编排的纯 Python 解释器

宏要同时驱动相图、属性、凝固、高通量和 ESPEI，最省事的写法是给每个命令复制
一份计算逻辑；这里反其道而行：`core/macro_engine.py` **只解析与编排**，每个
命令转交已有的 `plot_engine` / `scheil_engine` / `espei_engine` /
`high_throughput`，因此宏与界面按钮走的是同一条计算路径，结果一致、错误诊断
一致，也不会出现"界面能算、宏算不了"的分叉。

* **不碰 Qt**：结果经 `MacroCallbacks`（log / figure / table / database /
  selection）交给调用方；`workers/macro_worker.py` 把这些回调转成信号，
  UI 只负责显示。因此宏引擎可以在 `tests/test_macro.py` 里无界面直跑。
* **路径语义**：相对路径以**当前宏文件所在目录**为基准（不是进程 cwd），
  `INCLUDE` 同理；找不到时向上找一层父目录，方便 `macros/<来源>/` 里的宏
  直接引用仓库根目录的 `database/`。输出目录不存在会自动创建。
* **执行模型**：逐行解析（支持 `\` 续行、引号、`#` / `//` 注释、`$变量`），
  每行出错都补上"第 N 行："再抛 `CalculationError`；`INCLUDE` 深度上限 8，
  防止互相引用打穿栈。被引号整段包住的词不参与 `KEY=VALUE` 选项解析，
  所以 `PRINT "T=$temp"` 里的等号不会被当成选项。
* **交互式会话**：`MacroSession` 复用同一个 `_State` 与 `_Runner` 逐行执行
  （`run_line`，`numbered=False` 不带行号），数据库、元素、相、扫描和变量跨行
  保留；单行出错只抛给这一步，会话仍可继续。行级命令走
  `MacroCommandWorker`，与整宏共用 `MacroCallbacks` 和结果图交接逻辑。
  数据库在会话开始后才懒加载，避免"只敲了 ELEMENTS 就先读 TDB"。
* **帮助与补全**：`core/macro_help.py` 是纯数据表（不依赖 Qt），命令总览、
  单命令用法/说明/示例和补全词表都从这里出；别名由 `_COMMAND_ALIASES` 反推，
  保证帮助、补全与解释器不会各说各话。`?` / `? 命令` / `命令 ?` 由
  `help_request` 统一解析；补全是 `MacroTab` 自己按 token 边界替换，Tab 循环
  候选、上/下键翻历史，比 `QCompleter` 更适合"命令 + 上下文参数"的混合补全。
* **结果交接**：日志 / 结果表 / 数据库随时回传；**结果图要等 worker 结束
  才挂到中央画布**。原因是宏里 `DIAGRAM` 之后常跟 `EXPORT FIGURE`，worker 会
  对同一张 `Figure` 再 `savefig`：主线程一旦先把它包成
  `FigureCanvasQTAgg`，worker 线程再保存就会跨线程碰 QWidget（PyQt 抛
  "super-class __init__() of type FigureCanvasQTAgg was never called"），
  导出失败且画布被回写成 Agg 而空白。`MacroTab` 先暂存 `figure` 信号，
  在成功 / 失败 / 取消时统一 `_flush_figure()`。
  相图结果没有数据表，所以 `DIAGRAM` 之后的 `EXPORT DATA` 会明确报错而不是
  导出空文件。
* **官方示例**：`macros/` 按 pycalphad / scheil / ESPEI 分目录，共 22 个 `.pcm`
  宏；覆盖情况与上游不支持的示例（活性、黏度、带电相、参考态等）逐条写在
  `macros/README.md`，避免"看起来能用其实算不了"。

### 4.12 ESPEI 接入：设置必须与 run YAML 同构

ESPEI 的拟合结果对 `system.tags` 和 `generate_parameters.aicc_penalty_factor`
极其敏感。早期引擎只透传了 phase_models / datasets / 回归参数，官方 Cu-Mg
教程跑出来是 21 个参数（液相多两阶），与教程的 19 个不符；补上两项后才逐项
复现官方数值：

* `EspeiSettings.tags` 原样写入 `system.tags`。宏用简写
  `TAGS=dft:-idmix,-mag;estimated-entropy:-idmix,-mag,weight=0.1`，
  GUI 用同一套文本解析（也接受 JSON 对象或 `.json/.yaml` 文件）。
* `EspeiSettings.aicc_penalty_factor` 写入 `generate_parameters`，宏写法
  `AICC=LIQUID:HM=1.4,LIQUID:SM=1.4`。
* MCMC 的 `prior` 不再只支持 `zero`：`normal` 会带 `loc_relative` /
  `scale_relative`，与官方 `run_mcmc.yaml` 一致；`SCHEDULER=none` 映射为
  ESPEI 的 `scheduler: null`（单核串行），GUI 默认也改成单核。
* **数据集扫描必须递归**：官方示例把数据放在 `activity/`、`zpf/`、
  `fixed-configuration-thermochemical/` 三层子目录里，只 glob 顶层会得到
  0 个文件却"校验通过"。`list_datasets` 用 `rglob("*.json")`。
* **chdir 前先把路径钉成绝对路径**：ESPEI 把日志/trace 按相对路径落到
  工作目录，引擎会临时 `chdir(output_dir)`；若不先解析 phase_models /
  datasets，相对路径会指向错误的目录。
* 官方 Cu-Mg 的 31 个数据集 + 上述设置由
  `test_espei_official_cu_mg_generate_matches_tutorial` 锁死：必须得到
  19 个参数、液相只有 0/1 两阶，且 L0 常数项为 `-34437.588`。

---

## 5. 目录结构

```
pycalphad_gui/
├── ARCHITECTURE.md           # 本文档
├── README.md                 # 运行与自测说明
├── requirements.txt
├── pyproject.toml
├── pycalphad_gui/
│   ├── __init__.py
│   ├── app.py                # 启动入口（Agg 后端、主题、最大化启动）
│   ├── i18n.py               # 双语支持：词典装配 / tr / 整树遍历 / QSettings
│   ├── i18n_zh_en_ui.py      # 词典·界面文案
│   ├── i18n_zh_en_core.py    # 词典·引擎消息与元素名
│   ├── i18n_zh_en_macro.py   # 词典·宏页文案
│   ├── config.py             # 常量、配色、属性枚举、伪元素判定
│   ├── elements.py           # 118 元素数据 + 布局推导
│   ├── core/
│   │   ├── database_manager.py
│   │   ├── conditions.py     # 条件构造 + T1~T5 校验
│   │   ├── plot_engine.py
│   │   ├── property_engine.py
│   │   ├── high_throughput.py
│   │   ├── exporter.py
│   │   ├── macro_engine.py   # 宏解释器：解析 / 变量 / INCLUDE / 命令编排（不依赖 Qt）
│   │   ├── macro_help.py     # 宏命令帮助与补全词表（纯数据）
│   │   ├── digitizer.py      # 相图数字化：标定 / 去网格 / 边界吸附 / 区域采样（纯逻辑）
│   │   └── diagnostics.py    # 英文异常 → 中文可读诊断
│   ├── workers/
│   │   ├── base_worker.py
│   │   └── macro_worker.py
│   └── ui/
│       ├── main_window.py
│       ├── periodic_table.py
│       ├── phase_list.py
│       ├── condition_panel.py
│       ├── interactive_canvas.py
│       ├── digitize_canvas.py  # 图像画布：缩放/平移/十字与三线光标/区域回显
│       ├── digitize_tab.py     # 「数字化相图」页：五步流程 UI
│       ├── diagram_tab.py
│       ├── property_tab.py
│       ├── ht_tab.py
│       ├── scheil_tab.py
│       ├── espei_tab.py
│       ├── macro_tab.py      # 「宏命令」页：语法高亮 / 运行 / 日志 / 结果表 / 交互命令
│       ├── diagram_view.py
│       └── export_dialog.py
├── macros/                   # 官方示例宏（pycalphad / scheil / espei）
└── tests/
    ├── test_smoke.py         # 无 GUI 全流程冒烟（含数字化 6 项）
    ├── test_gui_headless.py  # 离屏 GUI 冒烟（含数字化与 i18n，构造真控件）
    ├── test_macro.py         # 宏解释器 + 示例宏端到端
    ├── test_espei_scheil.py  # ESPEI / Scheil 三方回归
    └── test_entry.py         # 启动入口（脚本模式 + 包模式）
```

---

## 6. 数据流示例（二元相图）

```
用户勾选 Al/Mg → 周期表选中
        │
        ▼
SelectionState{elements=('AL','MG'), excluded_phases=()}
        │
        ▼ 用户点"绘制二元相图"
PlotRequest(diagram_type='binary_ztpf', conditions={v.T:(300,1000,10), v.X('MG'):(0,1,0.02)})
        │
        ▼ 提交到 QThreadPool（PlotWorker）
PlotEngine.compute(...) → binplot(dbf, comps, phases, conds)         ← ~12 s
        │
        ▼ 主线程收 fig/ax
InteractiveCanvas.render(ax) + 绑定自定义交互
        │
        ▼ 用户加标签 / tie line
AnnotationStore → Exporter.export_png / export_csv
```

| T46 | `plot()` 的 autoscale 是"挂起请求"，首次绘制才真正套用 | 引擎造好裸 Figure 后挂到画布，`set_figure` 先 `set_autoscale_on(False)`——挂起请求被作废，viewLim 停在默认 **(0,1)**：图例在、坐标标签在、**线却画在视野外**（用户实测"不出图且进度条卡 66%"）。更阴险的是 `get_ylim()` 会顺手应用挂起请求，让探针误以为范围正常 | 引擎交付前必须 `axes.autoscale_view()` 把范围落定（`compute_property_curves` 末尾）；非有限值过滤，全 NaN 直接报可读错误 |
| T47 | 成功路径不收尾进度条 | 引擎最后一报是 2/3（"正在绘制"），`_on_success` 不更新进度条 → 成功了也永远停在 66%，用户以为还在算 | `_on_success` 推满 `_progress.setValue(maximum())`；失败 / 取消路径归零 |
| T48 | numpy 标量不是 Python `int` 的子类 | 高通量勾了"共存相数"——表头在、单元格全空。`len(phase_names)` 塞进 DataFrame 后，`DataFrame.iat` 读回是 `np.int64`；**`np.int64` 不继承 `int`**（只有 `np.float64` 继承 `float`），于是 `isinstance(x, (int, float, str))` 把它判成"不可显示"清成空串。同表其他列（float / str）都正常，所以只在整数列上暴露 | core 交付前用 `scalar_value()` 还原原生类型；UI 改用 `ht_tab._cell_text()`（`None` / NaN 显示空，其余一律 `str()`），不再用 `isinstance` 白名单过滤 |
| T49 | `eq.coords["Phase"]` 可能缺席 | 同时勾"液相分数"时整点判失败。`eq.coords` 里的 `Phase` 维度在部分数据库（V–Zr 只有 `IONIC_LIQ`）或无液相的解上直接不存在，下标访问抛 `KeyError`；且坐标是 `(vertices, phase)` 二维，原写法按第 0 维迭代拿到的是行数组 | `_liquid_fraction()` 用 `"Phase" in eq.coords` 判定 + `try/except KeyError` 兜底，坐标 `ravel()` 成一维再与 `NP` 对齐 |
| T50 | 全相 `Workspace` 永远只给平衡态 1D | 属性计算只画出"平衡相的曲线"，没有单个相的结果。引擎只建过一次 `Workspace(dbf, comps, phases, conds)`，而 **`get()` 在只有状态/组分条件时返回的是平衡态全局值（1D）**，与传几个相无关；代码里那套 `values.ndim > 1` 的"逐相分支"因此永远进不去（T44 遗留的死代码），于是把同一条线贴到每个相名下照样"看起来有 N 条" | 逐相 = `Workspace(dbf, comps, [该相], conds)` 逐个相各建一次，`get()` 才返回该相摩尔量（长度 = 采样点数）。三种曲线来源由 `options["curve_scope"]` 选择，默认 `per_phase` |
| T51 | 扫描轴切换不动"起/止"的量纲 | 扫 T 时"起/止/步长"还停在组分的 0→1 默认值，算出来的是 **0~1 K 的"温度"**，整条扫描全落空——用户只看到"没有结果"，和 T48 的空列叠在一起极难分辨 | `_on_xvar_changed()` 随轴切换 spinbox 的量程与默认值（T：300–1500 / 步长 50；组分：0–1 / 步长 0.02）并更新单位标签 |
| T52 | 元素勾选与后续面板的候选脱节 | 多元素库（cost507R：20 元素 / 191 相）里只勾了 Ti、V，属性页扫描轴却仍列着全部 20 个元素、Scheil 铺出 20 行摩尔分数输入——勾选形同虚设，用户以为算的是 Ti–V，随时可能被扫到 AL。根因：候选来自 `database.display_elements`（库内全部）而非用户的勾选；`diagram_panel` / `ht_tab` 还写了 `elements or database.display_elements`，勾空了更是整体回退 | 候选一律由 `database.sweep_candidates(elements)` 派生（`conditions.axis_candidates(database, elements)` 同款），空勾选就是空候选；新增 `components_safe()` 宽容推导，UI 联动路径不再走会抛异常的 `components_for` |
| T53 | 槽里的异常会让 PyQt6 直接 abort | 周期表允许勾库外元素，下游 `components_for()` 抛 `CalculationError`；这个调用在 `_on_elements_changed` → `_apply_context` 链上，而 **PyQt6 对"逃逸出槽函数的异常"是 `abort()`，不是打日志**——用户点一下库外元素，进程就没了 | `LoadedDatabase.components_safe()` 永不抛异常（坏符号单独回报），`_apply_context()` 逐个面板 `try/except` 兜住，状态栏用"已忽略 XXX：不在数据库中"如实说明；一个真元素都没勾时返回空而非 `[VA]`，避免空壳体系被当成有效组分放过去 |
| T54 | 按钮符号混合大小写 × 选中集全大写 | `set_selection` 里 `symbol in self._selected` 拿 `Al` 去比 `{'AL','B'}` 永远 False——**两字母元素在按钮上永远点不亮，却真实留在选中集里**。COST507 载入时预选 AL+B：B（单字母）恰好点亮、Al 不会；用户点掉 B、勾上 Ti/V，看不见的 Al 一直留在体系里，状态栏"Al + Ti + V"、下拉里有 AL，但周期表上根本找不到它被选中。单字母元素（B/V/N…）恰好大小写相同，所以 bug 只在两字母元素上暴露，且只在"经 set_selection 选中"时（预选、程序化设置） | 选中集统一存大写：`_on_button_clicked` / `_select_range` / `select_all_available` 存取都 `.upper()`，`set_selection` 比较 `symbol.upper() in self._selected`。配套：周期表顶部加"已勾选：Ti + V"摘要 + 清空按钮（选中状态必须肉眼可见）；多元素库载入不再预选前两个元素（AL+B 这种默认体系只会制造看不见的污染），二元库保留预选 |
| T55 | `clicked` 信号的 bool 参数漏进槽参数 | `add_btn.clicked.connect(self.add_row)`——PyQt6 的 `clicked` 带 `checked: bool`，点按钮等于调 `add_row(True)`，`set_target(True).strip()` 抛 `AttributeError`。初始化时 `add_row()` 无参调用所以正常，**只有真的点按钮才炸**；且逃逸出槽的异常在 PyQt6 里是 abort 进程 | 改 `lambda _checked: self.add_row()`。凡是把无参方法直接绑到带参信号上都要过一遍参数签名 |
| T56 | 扫描维度候选塞进 P/N | `set_target_candidates` 把 `STATE_VARS`（T/P/N）整组加进候选。P 走"固定条件"输入框、N（摩尔数）在相图计算没有使用场景，摆在下拉里只会诱导用户扫一个没意义的量 | 候选只追加 `["T"]`；引擎侧 ConditionPlan 仍支持扫 P/N，只是界面不列出 |
| T57 | pycalphad 0.11 步进映射可能全军覆没 | 三元等温截面走 `ternplot` 时，`TernaryStrategy.generate_automatic_starting_points` 沿三条边做步进映射找起点；当起点（如纯 Al 端的 LIQUID）的第一步恰好跨进两相区，全局最小检查（能量差 ~0.08 J/mol）否决该步，框架**既不缩步长也不换方向，直接 0 节点收场**。随后 `plot_ternary` 在空 tie line 上 `np.concatenate([])` 崩溃。cost507R 的 Ti–Al–V @1200 K 三种温度、任意相列表均复现，而 `equilibrium` 单点求解完全正常 | 引擎不再一步调 `ternplot`：先手动 `TernaryStrategy` + `do_map()`，tie line 非空才走 `plot_ternary`；为空或抛异常则退回**网格法** `_render_ternary_grid()`——一次向量化 `equilibrium` 求整个三角网格，按稳定相组合着色画在 `projection='triangular'` 上（图题标注"网格法"）。另：只勾两个真元素时 `TernaryStrategy` 因找不到"不在轴上的第三元素"直接 IndexError，引擎前置校验给中文提示 |
| T58 | 同名双顶点（混溶隙）+ 按名去重 = 相图缺一块 | alcrni @1400K 出现 `B2+B2`、`L12_FCC+L12_FCC` 标签——**同一相占据两个顶点**（混溶隙/有序-无序两分支），各顶点成分不同。旧网格法按相名去重，把混溶隙的 tie line 整个丢掉，两相区只剩"单相"残段；连边界时若按名字取顶点索引，pycalphad 顶点顺序在相邻格点间还会交换，连线交叉成"梯子"；跨单相区两侧的两相区贸然连同名端点，又会叠出横穿相区的粗带 | 网格法重写为 Thermo-Calc 经典线式（`_ternary_lines_view`）：① 稳定相**不按名去重**，保留全部顶点，混溶隙 tie line（B2–B2）照画；② 相边界由相邻格点的同相端点**最近邻配对**相连（端点恰在 binodal 上），跨不同相组合不连；③ 单相区内部留白，仅沿三角形边缘描相色边线，黑描边保证轮廓完整；④ 等边三角形手绘坐标轴（`set_axis_off` + 自绘刻度），旧版铺色视图保留为 `grid_fill` 选项 |
| T59 | 旧版填充样式：轴标签飘、边缘留白、边界锯齿 | 旧 fill 视图用 `projection='triangular'` + 方块 marker：① 纵轴标签被 matplotlib 甩到很远的地方；② 方块 marker 只盖住格点，三角形边缘留下锯齿状白色缺口；③ 相边界就是格点列的锯齿边 | fill 视图重写为官网 ternplot 风格（`_ternary_fill_view`）：对全部有效格点做 **Delaunay 三角剖分**——(0,0)/(1,0)/(0,1) 三顶点都是网格节点，凸包恰为整个成分三角形，铺满无缺口；只有三个节点同属一个单相的三角形才着色（相色），着色三角形的外边缘描黑，边界落在网格单元中点（锯齿细一半）；两相区留白。坐标轴与线式共用 `_make_ternary_axes`（等边三角形 + 自绘刻度，标签紧贴轴）。坑：`PolyCollection.get_offsets()` 返回的是偏移（默认 [[0,0]]）不是顶点，几何信息在 `get_paths()` 里 |
| T60 | 测试数据库依赖 site-packages 绝对路径 | `test_smoke.py` 的 `DB_DIR` 硬编码本机 Python 安装路径，换机器/换环境直接挂；用户数据库（cost507R 等 13 个 TDB）也散落在 OpenCalphad 安装目录 | pycalphad 自带测试数据库复制到 `tests/databases/pycalphad/`（46 个文件），测试改用相对路径；pycalphad / espei / scheil 官方源码包的测试目录复制到 `tests/third_party/`（默认不参与 pytest 收集，见 `tests/conftest.py`）；用户数据库复制到项目根 `database/` |
| T61 | TernaryStrategy 的成分条件传 np.linspace 全量数组 = 0 节点 | `TernaryStrategy` 对条件值**形式敏感**：X 条件传 `(0, 1, step)` 三元组正常收敛，传等价的 `np.linspace` 全量数组则起点步进全部失败、0 tie line——官方 Cr-Fe-Nb @1323K 算例都能复现（元组 9 tie lines，数组 0 条）。**T57 里 cost507R"映射全军覆没"实为同一根因**，换三元组后 cost507R Ti–Al–V 映射正常收敛；此前网格法兜底掩盖了真因 | 引擎组装 `TernaryStrategy` 条件前做规范化：ndarray 条件转 `(first, last, step)` 三元组（`map_conds`），标量 T/P/N 原样传；网格法兜底仍用原数组条件。同时按官方文档补齐填色路径：映射收敛 + 勾选填色 → `_plot_shaded_ternary()`（官网 `plot_shaded_ternary` 同款：整幅铺单相淡蓝底，不变式画黄色三角 patch，tie line 首尾相接成两相白多边形）；映射未收敛仍退网格法 |
| T62 | eqplot 只传 x 不传 y → 两轴同一变量、数据退化成对角线 | 三元平衡态图原先只显式传 `x`，`y` 交给 eqplot 自动补齐（`y = indep_comps[1]`）；而 `indep_comps` 是**按变量名 `str` 排序**的（`['X_AL','X_V']`），当 `x` 恰好等于排序后的第二个独立组分时（用户扫 V、Al，x=X(V)），`y` 又被补成 `X(V)` —— 两轴同名，eqplot 拿 X(V) 同时当横纵坐标，三角投影里退化成一条彩色对角线；纵轴标签还压在刻度数字上（eqplot 默认 `set_label_coords(0.275 - 1/figwidth, 0.5)`，画布小时必然重叠） | 三元分支显式传两个不同的组分：`x=v.X(comps[0])`、`y=v.X(comps[1])`；二元分支的 y 由**被扫描的** T/P 决定（不再用"只要有 T 扫描就传 v.T"的近似写法，扫 P 时也正确）。三元投影另做排版微调：画布放大到 8.6×6.4、刻度字号 10、y 轴标签转 60° 并移到 axes 坐标 `(-0.02, 0.45)` 让开刻度数字 |
| T63 | 相图数字化：网格线检测与擦除的四连坑 | ① **虚线判定**：最初按"最长连续段"筛网格线，16 亮 / 24 暗的虚线整条被否掉 → 改用 **max-gap 比值**（最长暗缺口 / 区域跨度 ≤ 10%）才认；② **跨度分母用错**：先拿整幅图算 span，短网格线永远不够长 → 分母必须是**墨迹 / 标定区域自身的投影跨度**（`_extent_along`）；③ **三元斜线漏检**：理论 60°/120° 的光栅化斜线在 1 px 分箱里铺散到相邻箱，且弦长天然比边长短 → 收集峰值的 **±1 箱**邻域 + 峰值下限 `max(3, 0.15*max)`，三元 `span_ratio` 单独放宽到 0.35；④ **擦不干净**：按理论角度擦，实际线条偏 1.5° → 350 px 长就偏 8 px，留一道残影 → 记录并使用实际角度 `angle_used`，再叠 **3×3 墨迹膨胀**（5×5 会吃掉约 20% 的真实相边界）并多轮擦除 | ① `detect_grid_lines` 用 max-gap 而非 longest-run；② `span_source = region or mask`；③ 分箱邻域 ±1 + `peak_floor`，三元/二元分别给 `span_ratio`；④ `remove_grid_lines` 用 `angle_used` 擦几何条带（`|s-offset|<=2.0`）+ `binary_dilation(..., np.ones((3,3)))`，最多 3 轮 |
| T64 | 数字化：标定框被当网格线擦掉 → 区域取不到边界 | 矩形/三角形边框本身就是"贯通整个坐标区域的直线"，必然被网格线检测命中并擦除；之后在框附近点边界就找不到任何墨迹，采样 0 行 | `snap_to_boundary` 找不到点时回退到 `project_to_polygon()`（容差 10 px），把点击投影到标定区域多边形上；测试里"第二个区域贴着边框"这一路必须复现，否则该分支是死代码 |
| T72 | **运行宏时窗口底端被挤出屏幕、右侧「计算」面板被宏页撑宽、底部日志被挡住**（用户实测三处） | 探针：`MacroTab.minimumSizeHint().width() == 838`（示例路径下拉 534px + 三个 80px 按钮同排），而 `QTabWidget` 的最小尺寸取**所有页面的并集**——即使宏页没显示也参与计算，右栏被顶到 607–854px；`EspeiTab` 整表单最小高 826px，把整窗最小高抬到 988–1058px（真机可用高 1032），最大化时底部的日志 / 进度 / 状态栏被压出可视区 | ① 右侧 7 个子页统一包进 `QScrollArea(widgetResizable=True)`，切断单页最小高 / 宽对窗口的绑架，放不下时由滚动条兜底；② 宏页顶部改三行、去掉冗余的"示例"标签（下拉占位已说明）、示例下拉用 `QSizePolicy.Ignored` + 72px 下限、语法帮助改成 28px 的"?"，页面最小宽 838→265px；③ `resizeEvent` 中窗口缩小时按比例收窄左右停靠面板（放大时新增空间全部给画布），并保证中央画布 ≥360px。回归：`test_side_panels_do_not_inflate_window_and_shrink_proportionally`（窗口最小高 ≤700、宏页最小宽 ≤300、追加日志 / 切页不改变窗口与右栏宽度、缩小不反向变宽）。教训：QTabWidget 的最小尺寸是**所有页面的并集**，隐藏页也会撑窗口；长下拉的 sizeHint 必须从布局里摘掉，否则单这一项就能决定整窗最小宽 |
| T71 | 全局 QSS 把小按钮的内容区挤没了 + 数字框步进箭头反复渲染不正常（用户两次截图反馈） | ① 全局 `QPushButton { padding: 6px 14px }` 先扣 28px 才轮到文字：24px 的"×"删除按钮内容区为负 → 空白；44px 的"清空"只剩半个字。② `QTabBar` 的滚动 ◀▶ 是 QToolButton，被全局 `QToolButton { padding: 5px 10px }` 挤成空白。③ 数字框一旦被 QSS 管外框，步进按钮的默认箭头就没人画了（只剩裁剪碎片）；改用 CSS 三角箭头在 Windows 上仍渲染成小方块（用户第二次实测不过） | ① 新增 `QPushButton#iconBtn { padding: 0 }`，×/清空挂 objectName（清空 44→56px）；② `QTabBar QToolButton { padding: 0; min-width: 16px }`；③ 最终按用户要求把 `::up-button/::down-button` 设为 width:0/height:0——数字框外观就是普通输入框，校验/范围钳制/键盘上下键/滚轮保留（全局 37 个数字框统一生效）。**教训：offscreen 抓图验证前必须先 `apply_theme(app)`**——主题只在 `app.py main()` 里挂，探针直接构造 QApplication 时抓到的是无样式渲染，会得出"已修好"的假结论（本次因此返工一轮） |
| T70 | `QDoubleSpinBox` 的 `decimals` 同时管"显示几位"和"取值精度"，且**超位数输入被静默丢弃**（用户要求：温度显示 1 位、成分 3 位，但输入可以更多） | 设 `setDecimals(1)` 显示省事，但输入 300.25 会被直接改写成 300.3——丢精度；反过来 decimals=4 显示啰嗦，而输 0.333333 时 Qt 把它标成 Intermediate，回车/失焦**不提交**、文本弹回 0.0（实测）。另有 f-string `.1f` 是银行家舍入（300.25 → 300.2），与直觉不符 | 新增 `ui/spinboxes.py` 的 `DisplaySpin`：`decimals` 保持存储精度，`textFromValue` 按 `display_decimals` 渲染（`Decimal.quantize(ROUND_HALF_UP)` 半进位）；`validate` 一律 `Acceptable` + 自写 `valueFromText`（`QLocale.toDouble` 解析、乱码回退原值、范围仍由 `setValue` 钳制）。扫描行显示位数跟量纲联动：T→1、P→0、成分→3（`set_target` 的"候选未填提前返回"分支也要应用）。回归：`test_display_spin_separates_display_and_value` |
| T69 | **窗口最小宽被"文本驱动的最小尺寸"顶爆**（用户实测：整个界面比屏幕还宽、最大化也塞不进去） | 探针实测：`MainWindow.minimumSizeHint().width() == 4914`。四个来源：① 提示 QLabel 不开 `wordWrap` 时最小宽 = **整句**宽度（英文手势提示一行 2409px）；② QHBoxLayout 一行的最小宽 = **各项相加**（高通量 5 个复选框横排 + "并发/模式/按钮"挤一行 → 1762px）；③ 英文译文比中文长得多，所有表单控件的最小宽跟着膨胀；④ 右侧子面板标签间的"—"断线是 `QTabBar.drawBase` 的通长基线从 documentMode 标签缝隙里透出来的，且 `QTabWidget#xxx::tab` 是**无效 QSS 选择器**（Qt 只认 `QTabWidget::pane` / `QTabWidget::tab-bar`，标签样式必须写 `QTabWidget#xxx QTabBar::tab`）——之前写的紧凑标签样式从未生效 | ① 所有信息/提示标签 `setWordWrap(True)`；② 复选框改 QGridLayout 3 列、"运行行"拆两行、扫描行改两行式（下拉+删除一行，起止步长一行）；③ `_relax_min_widths()`：对最小宽超标的 QComboBox/QCheckBox/QGroupBox/QPushButton 调 `setMinimumWidth(cap)`（按钮 150、其余 240）——**显式 minimumWidth 在布局计算中优先于 minimumSizeHint**，这是让表单能收缩的唯一开关；④ `tabBar().setDrawBase(False)` + 修正选择器。右面板宽度 = `showEvent` 里按屏幕可用宽度的 20% 动态设定（260–420px），初始窗口尺寸也按屏幕钳制。注意：`minimumSizeHint()` 是**缓存值**，加了显式 minimum 后它不会变，探针里看到的"还是很大"未必是真的——以 `grab()` 实拍为准 |
| T68 | 界面双语的三处"明明翻了却没翻" | ① **停靠面板标题**：`QDockWidget` 停靠状态下 `isWindow()` 是 False，`apply_to` 的 windowTitle 分支走不到——「元素与相」「计算」两块标题漏翻；② **QSpinBox 的 specialValueText**：ESPEI 页 Ridge α 的"关闭（普通最小二乘）"不在 text/suffix 里，是独立属性；③ **引擎生成的图面文字**："温度 T (K)"、"（无有限值）"是后台线程写进 Figure 的，整树遍历扫不到 QWidget 之外的 Text。另有 **`Tick.get_label()` 陷阱**：它继承自 `Artist.get_label()`，返回的是 **str** 而不是刻度的 Text 对象，对它调 `.get_text()` 直接 AttributeError | ① `apply_to` 对 `QDockWidget` 单独翻 windowTitle；② `QAbstractSpinBox` 补 `specialValueText`；③ `set_figure()` 挂画布时就地 `apply_to_figure()`；刻度文本改用 `tick.label1`。回归：`test_i18n_dictionary_is_complete`（AST 全量字面量、f-string 按片段、译文零汉字残留）+ `test_language_switch_leaves_no_chinese_in_english_mode`（控件树级复核） |
| T66 | `QPainter` 的绘制 API **一个 float 都不收**（用户实测：一打开图片就崩） | `drawPixmap(x, y, w, h, pm)` 里混进了 `QPointF.x()`（`_offset` 是 `QPointF`）与缩放后的 `px_w/px_h` —— sip 直接 `TypeError: arguments did not match any overloaded call`，且打印完 traceback 后可能 abort 进程。与 T22（`drawLine`）同源：Qt 的绘制重载全是 `int`，`QPointF` / `QRectF` 只在 **`drawPolygon` / `drawEllipse` / 以 Rect 为第一参的重载**里合法 | 绘制坐标一律 `int(round(...))`；图片改用 `drawPixmap(QRect(x, y, w, h), pixmap)`（Rect 重载收 `QRect`，语义还是"缩放到这个矩形"）。`w/h` 用 `max(v, 1)` 兜底，避免极小缩放时 0 宽矩形 |
| T67 | **离屏环境不触发 `paintEvent`** → 绘制路径是"没人跑过"的盲区 | 所有 GUI 测试都在 `QT_QPA_PLATFORM=offscreen` 下跑，而 offscreen **不会真正派发绘制事件**。于是 `paintEvent` 里既有 bug 也全绿：本次除 T66 的 float 之外，还潜伏着 `self._draw_regions(painter)` —— **这个方法根本不存在**（区域绘制被写进了 `_draw_points` 里），只是前面的 `drawPixmap` 先抛错，永远轮不到它执行 | 新增 `test_digitize_canvas_paint_uses_int_coordinates`：**显式调用 `canvas.paintEvent(None)`**（在 Python 层 try/except，避免 sip abort 把整个测试进程带走），并用奇数尺寸 + 小数 offset/scale 保证坐标一定是非整数，三种光标模式各画一遍。教训：凡是有自定义 `paintEvent` 的控件，都必须有一条"手动触发绘制"的用例，否则那部分代码等于没有测试 |
| T65 | 数字化：Qt 图像通道的三处静默失败 | ① `QImage(rgb.data, w, h, QImage.Format_RGB888)` **借用** numpy 缓冲区，函数返回后底层内存即失效 → 必须 `.copy()`；② `QClipboard.image()` 在没有图像时返回**空的 QImage**（不是 None），直接转数组会得到全 0 或崩溃 → 先 `isNull()`，再回退到 `mimeData().urls()` 走文件路径；③ 沙箱 / 无显示器环境下 `QWidget.grab()` 会 abort（exit 127），截图只能另想办法 | `array_to_pixmap()` 内 `.copy()`；`_on_paste_image` 三级回退（image → urls → 提示）；功能演示图改用 matplotlib 出图（`apply_cjk_font()` 先装中文字体，否则汉字全是豆腐块） |
