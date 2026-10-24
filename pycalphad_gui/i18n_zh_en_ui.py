"""界面文案词典（中文 → 英文）。

> 与 ``i18n.py`` 的引擎配套。**key 必须是源码里出现的中文字面量原文**
> （含空格、换行、全角标点），运行时按整串精确匹配；改源码中文案时同步这里。
>
> 不收录：纯数据（元素符号、相名 ``BCC_A2``、颜色名、数值）、
> 语言自称（``English`` / ``中文``，否则语言按钮上的字会跟着变）。

按源文件分组，便于对照维护。
"""

from __future__ import annotations

from typing import Dict

UI_ZH_EN: Dict[str, str] = {

    # ================================================== ui/main_window.py
    "元素与相": "Elements & Phases",
    "相图计算": "Diagram Calculation",
    "属性": "Properties",
    "高通量": "High Throughput",
    "Scheil 凝固": "Scheil Solidification",
    "ESPEI 拟合": "ESPEI Fitting",
    "数字化相图": "Digitize Diagram",
    "计算": "Calculation",
    "计算面板": "Calculation Panel",
    "主工具栏": "Main Toolbar",
    "文件": "File",
    "视图": "View",
    "帮助": "Help",
    "退出": "Quit",

    # ---- 语言切换（语言自称本身不收，见本文件开头说明）----
    "切换界面语言": "Switch interface language",
    "界面语言已切换。": "Interface language switched.",

    "请先打开一个 TDB / DAT 热力学数据库":
        "Open a TDB / DAT thermodynamic database to begin",
    "尚未载入数据库": "No database loaded",
    "载入后即可看相图：<br>元素周期表挑组分 → 相列表决定算哪些相 → 点「计算并绘制」":
        "Load one to start plotting:<br>pick components in the periodic table → "
        "choose phases in the phase list → click 'Compute &amp; Plot'",
    "打开数据库…": "Open Database…",
    "快捷键 Ctrl+O；也可以直接把 .tdb 文件拖进窗口":
        "Shortcut Ctrl+O; you can also drag a .tdb file into the window",
    "Ctrl+O，或把 .tdb 拖进窗口": "Ctrl+O, or drag a .tdb into the window",
    "载入 TDB / DAT 数据库": "Load a TDB / DAT database",
    "打开热力学数据库": "Open Thermodynamic Database",
    "Thermo-Calc 数据库 (*.tdb *.dat);;所有文件 (*)":
        "Thermo-Calc database (*.tdb *.dat);;All files (*)",

    "导入图像": "Import Image",
    "导入一张相图图片用于数字化（Ctrl+Shift+O）":
        "Import a phase-diagram image for digitization (Ctrl+Shift+O)",
    "粘贴图像": "Paste Image",
    "把剪贴板里的截图直接贴进来（Ctrl+Shift+V）":
        "Paste a screenshot straight from the clipboard (Ctrl+Shift+V)",
    "导入相图图像": "Import Phase-Diagram Image",
    "图像文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;所有文件 (*)":
        "Image files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All files (*)",
    "剪贴板里没有图像": "No image in the clipboard",
    "图像导入失败": "Image Import Failed",
    "滚轮缩放 · 中键拖动平移 · 左键取点 · 右键删点（数字化流程见右侧「数字化相图」）":
        "Wheel to zoom · middle-drag to pan · left-click to pick · right-click to "
        "delete (digitization flow is in 'Digitize Diagram' on the right)",

    "计算并绘制": "Compute & Plot",
    "按右侧条件算出相图": "Compute the diagram from the conditions on the right",
    "取消": "Cancel",
    "取消当前计算": "Cancel the running computation",
    "导出图像…": "Export Image…",
    "导出 PNG / SVG / PDF / JPG": "Export PNG / SVG / PDF / JPG",
    "复位视图": "Reset View",
    "恢复初始坐标范围": "Restore the initial axis ranges",
    "清除标注": "Clear Annotations",
    "移除全部标注与连线": "Remove all labels and tie lines",
    "对数轴": "Log Axes",
    "切换 X / Y 轴对数坐标": "Toggle logarithmic X / Y axes",
    "交互说明": "Interaction Guide",
    "鼠标手势与功能一览": "Mouse gestures and features at a glance",
    "已打开交互说明": "Interaction guide opened",

    "数据库加载失败": "Database Load Failed",
    "无法打开": "Cannot Open",
    "只支持 .tdb / .dat 数据库文件，或图片（":
        "Only .tdb / .dat database files or images are supported (",
    "读取上次目录失败，回退到用户目录":
        "Could not read the last directory; falling back to the home folder",
    "写入上次目录失败": "Could not remember the last directory",
    "文件不存在：": "File not found: ",
    "载入数据库 %s": "Loaded database %s",
    "面板 %s 刷新失败：%s": "Panel %s failed to refresh: %s",
    "已载入 ": "Loaded ",
    "｜元素 ": " | elements: ",
    " 个｜相 ": " | phases: ",
    " 个｜读取 ": " | read in ",
    "｜请在周期表勾选元素后开始计算":
        " | tick elements in the periodic table to start",
    "已忽略 ": "Ignored ",
    "：不在数据库 ": ": not in database ",
    " 中，未参与计算": " — excluded from the calculation",
    "体系：—（请先在周期表勾选元素）":
        "System: — (tick elements in the periodic table first)",
    "体系：": "System: ",

    # ---- 交互说明对话框 ----
    "左键单击图上空白处": "Left-click empty space on the plot",
    "就地输入并放置标注（默认带该处相名）":
        "Type inline and place a label (defaults to the phase name there)",
    "拖动标注": "Drag a label",
    "移动标注位置": "Move the label",
    "双击标注": "Double-click a label",
    "就地改名": "Rename it in place",
    "Shift + 左键拖动": "Shift + left-drag",
    "画 tie line（实时预览，松开落笔）":
        "Draw a tie line (live preview, released to commit)",
    "右键单击标注 / 连线": "Right-click a label / tie line",
    "删除它": "Delete it",
    "右键拖动 / 中键拖动": "Right-drag / middle-drag",
    "平移视图": "Pan the view",
    "左键拖动空白": "Left-drag empty space",
    "框选缩放（虚线橡皮筋）": "Rubber-band zoom (dashed marquee)",
    "滚轮": "Mouse wheel",
    "以光标为锚缩放": "Zoom anchored at the cursor",
    "双击空白": "Double-click empty space",
    "把图例挪到任意位置": "Move the legend anywhere",
    "拖动图例（legend）": "Drag the legend",
    "周期表：Shift + 点击": "Periodic table: Shift + click",
    "框选一段元素范围": "Select a range of elements",
    " 交互说明</h3><p style='margin:4px 0 10px 0; color:#7a8494;'>所有交互都由鼠标手势直接完成，不需要切换模式。</p><table cellspacing='0'>":
        " interaction guide</h3><p style='margin:4px 0 10px 0; color:#7a8494;'>"
        "Every interaction is a direct mouse gesture — there are no modes to switch.</p>"
        "<table cellspacing='0'>",

    # ================================================== ui/diagram_panel.py
    "设定好扫描条件后点「计算并绘制」":
        "Set the sweep conditions, then click 'Compute &amp; Plot'",
    "计算组分：": "Components: ",
    "⚠ 当前扫描网格约 ": "⚠ The current sweep grid is about ",
    " 点，计算可能非常缓慢": " points — the computation may be very slow",
    "请先加载数据库": "Load a database first",
    "请先在周期表中选择元素": "Select elements in the periodic table first",
    "绘制相图": "Plot Diagram",
    "正在取消…": "Cancelling…",
    "\n条件：": "\nConditions: ",
    "\n耗时 ": "\nElapsed ",
    "绘制完成": "Plot finished",
    "计算失败": "Computation Failed",
    "已取消": "Cancelled",
    "已取消计算": "Calculation cancelled",

    # ================================================== ui/diagram_view.py
    "左键单击加标注 · 双击标注改名 · Shift+拖动画连线 · 右键单击删除 · 右键/中键拖动平移 · 左键拖动框选 · 滚轮缩放 · 双击空白复位":
        "Left-click to label · double-click a label to rename · Shift+drag to draw a "
        "tie line · right-click to delete · right/middle-drag to pan · left-drag to "
        "rubber-band zoom · wheel to zoom · double-click empty space to reset",
    "尚未绘制": "Nothing plotted yet",
    "耗时 ": "Elapsed ",
    "计算中… %p%": "Computing… %p%",
    "还没有可操作的图像": "No diagram to work with yet",
    "已清除标注": "Annotations cleared",
    "还没有可导出的图像": "No diagram to export yet",
    "导出失败：": "Export failed: ",
    "已导出 ": "Exported ",
    "光标：x=": "Cursor: x=",

    # ================================================== ui/condition_panel.py
    "相图类型": "Diagram Type",
    "类型": "Type",
    "二元 T–X：1 个组分扫描 + 1 个温度扫描\n三元等温截面：2 个组分扫描，温度固定":
        "Binary T–X: 1 composition sweep + 1 temperature sweep\n"
        "Ternary isothermal section: 2 composition sweeps, temperature fixed",
    "扫描维度": "Sweep Dimensions",
    "+ 添加扫描维度": "+ Add sweep dimension",
    "删除该扫描维度": "Remove this sweep dimension",
    "固定条件": "Fixed Conditions",
    "标准大气压 101325 Pa": "Standard atmosphere, 101325 Pa",
    "温度 T (K)": "Temperature T (K)",
    "压强 P (Pa)": "Pressure P (Pa)",
    "绘图选项": "Plot Options",
    "显示 tie line（两相连线）": "Show tie lines (two-phase links)",
    "关掉可加快大体系的计算与出图速度":
        "Turning this off speeds up calculation and plotting for large systems",
    "标注三相点节点": "Label three-phase nodes",
    "填色相区（官网 shaded 风格：二元 / 三元）":
        "Shaded phase regions (binary & ternary)",
    "勾选后：二元相图改用 BinaryStrategy 映射并按官网 plot_shaded_binary 填色（单相区淡蓝底、两相区白色、黑色相界、内向刻度）；三元截面按 plot_shaded_ternary 填色（单相区淡蓝、两相区白色 tie line 多边形、三相区黄色三角形）。映射未收敛时退回常规绘制":
        "When enabled: binary phase diagrams use BinaryStrategy mapping with official plot_shaded_binary shading (light-blue single-phase base, white two-phase regions, black boundaries, inward ticks); ternary sections use plot_shaded_ternary shading (light-blue single-phase, white tie-line polygons for two-phase, yellow three-phase triangles). Falls back to regular plotting if the mapping does not converge",

    # ================================================== ui/property_tab.py
    "属性设置": "Property Settings",
    "曲线来源": "Curve Source",
    "逐相：每个相单独求解，画的是该相自身的 G/H/S/Cp（含亚稳相）\n平衡态：只画全局最稳定相的结果\n两者都画：逐相曲线 + 平衡态虚线参照":
        "Per phase: each phase solved on its own, plotting its own G/H/S/Cp "
        "(metastable phases included)\nEquilibrium: only the globally most stable "
        "phase\nBoth: per-phase curves plus a dashed equilibrium reference",
    "参与逐相计算的相": "Phases (per-phase)",
    "全选": "Select all",
    "全不选": "Deselect all",
    "扫描轴": "Sweep Axis",
    "(摩尔分数)": "(mole fraction)",
    "起 / 止 / 步长": "start / stop / step",
    "固定温度 T (K)": "Fixed temperature T (K)",
    "扫描温度时钉死的摩尔分数；扫描组分时不起作用":
        "Mole fraction pinned while sweeping temperature; has no effect when "
        "sweeping composition",
    "固定组分 X": "Fixed composition X",
    "计算属性曲线": "Compute property curves",
    "尚未计算": "Not computed yet",
    "导出曲线数据…": "Export curve data…",
    "请选择扫描轴": "Choose a sweep axis",
    "步长必须大于 0": "Step must be greater than 0",
    "采样点过多，请增大步长": "Too many sample points — increase the step",
    "请至少勾选一个相（也可先把曲线来源切到「平衡态」）":
        "Tick at least one phase (or switch Curve Source to 'Equilibrium' first)",
    "属性计算 ": "Property computation ",
    " 条曲线｜": " curve(s) | ",
    "｜耗时 ": " | elapsed ",
    "⚠ 未出曲线的相：": "⚠ Phases with no curve: ",
    "提示：当前只看平衡态，切到「逐相」可看每个相各自的曲线":
        "Tip: currently showing equilibrium only — switch to 'Per phase' to see "
        "each phase's own curve",
    "属性计算完成": "Property computation finished",
    "还没有可导出的数据": "No data to export yet",

    # ================================================== ui/ht_tab.py
    "任务设置": "Job Settings",
    "并发": "Concurrency",
    "模式": "Mode",
    "并发计算线程数（选择进程池时即进程数）":
        "Concurrent workers (processes when the process pool is selected)",
    "线程池（推荐）": "Thread pool",
    "进程池（CPU 密集）": "Process pool (CPU-bound)",
    "线程池：Database 共享内存、取消及时\n进程池：规避 GIL，启动开销较大":
        "Thread pool: shares the Database, cancels promptly\n"
        "Process pool: bypasses the GIL, higher start-up cost",
    "开始高通量扫描": "Run sweep",
    "就绪": "Ready",
    "导出结果…": "Export results…",
    "⚠ 预计 ": "⚠ Estimated ",
    " 个计算点，耗时可能很长": " points — this may take a long time",
    "请至少设置一个扫描维度": "Set at least one sweep dimension",
    "请至少选择一个输出指标": "Select at least one output metric",
    "高通量扫描": "High-Throughput Scan",
    " 个点…": " points…",
    "正在计算 ": "Computing ",
    " 个失败": " failed",
    "（已取消）": " (cancelled)",
    " 点，耗时 ": " points, elapsed ",
    "✅ 完成 ": "✅ Finished ",
    "高通量扫描完成": "High-throughput scan finished",
    "没有可导出的结果": "No results to export",
    "失败点 ": "Failed points ",

    # ================================================== ui/scheil_tab.py
    "成分（摩尔分数）": "Composition (mole fraction)",
    "请在左侧周期表中选择元素后载入数据库，这里会自动列出":
        "Tick elements in the periodic table on the left and load a database; "
        "this list fills in automatically",
    "元素": "Element",
    "模拟参数": "Simulation Settings",
    "凝固模型": "Solidification model",
    "起始温度，必须落在单一液相区内":
        "Starting temperature; must lie in the single-liquid region",
    "起始温度 T (K)": "Start temperature T (K)",
    "温度步长 / 停止条件": "Temperature step / stop condition",
    "留空则自动推断（如 IONIC_LIQ）":
        "Leave empty to infer automatically (e.g. IONIC_LIQ)",
    "液相相名": "Liquid phase name",
    "+ 添加固定成分": "+ Add fixed composition",
    "二元 T–X：1 个组分扫描 + 1 个温度扫描\n三元等温截面：2 个组分扫描，温度固定\nStep 图：1 个扫描维度，其余量固定\nIsopleth：1 个组分扫描 + 1 个温度扫描 + 至少 1 个固定成分":
        "Binary T-X: 1 composition sweep + 1 temperature sweep\nTernary isothermal section: 2 composition sweeps, temperature fixed\nStep plot: 1 sweep axis, everything else fixed\nIsopleth: 1 composition sweep + 1 temperature sweep + at least 1 fixed composition",
    "相分数 NP(*)": "Phase fractions NP(*)",
    "相中元素含量 X(相, 元素)": "Element content in phase X(phase, elem)",
    "Degree of ordering（有序度）": "Degree of ordering",
    "Site fraction（占位分数）": "Site fraction",
    "目标相": "Target phase",
    "相中元素含量": "Element content in phase",
    "属性量": "Property",
    "如 CPM / HM / SM": "e.g. CPM / HM / SM",
    "属性量": "Property",
    "自动生成映射起点（三元截面）": "Auto-generate mapping starting points (ternary)",
    "相区可能不与三角形三条边相连（如 Al-Cu-Y 高温截面），沿边搜索的起点会一无所获。勾选后先按官方流程生成起点；映射仍为空时自动在三角形内部补节点重试。仅三元截面有效":
        "Phase regions may not touch the triangle edges (e.g. Al-Cu-Y at high T), leaving the axis-edge search empty. When enabled, starting points are generated per the official workflow; if the mapping is still empty, interior nodes are seeded and the mapping is retried. Ternary sections only",
    "自适应步长（推荐；关闭时 scheil 0.3.0 会 KeyError）":
        "Adaptive step (recommended)",
    "关闭时 scheil 0.3.0 会抛 KeyError，仅用于兼容旧版本":
        "Without it scheil 0.3.0 raises KeyError (legacy only)",
    "开始凝固模拟": "Start solidification simulation",
    "导出模拟结果…": "Export simulation results…",
    "请先在周期表中选择元素并导入数据库":
        "Tick elements in the periodic table and load a database first",
    "未选元素": "No element selected",
    " 个元素，只有勾选的会出现下方。摩尔分数之和不必恰好为 1，剩余部分由空位（VA）补齐；最后一个填入的元素会被当作溶剂（scheil 只接受独立组分）。":
        " elements; only the ticked ones appear below. The mole fractions do not "
        "have to sum to 1 — the remainder is filled with vacancies (VA). The last "
        "element filled in is treated as the solvent (scheil accepts independent "
        "components only).",
    "｜库内共 ": " | database contains ",
    " 的摩尔分数": " mole fraction",
    "⚠ 请至少填写一个元素的摩尔分数":
        "⚠ Fill in the mole fraction of at least one element",
    "请填写成分": "Fill in the composition",
    "Scheil 凝固模拟": "Scheil Solidification Simulation",
    "凝固模拟完成，": "Solidification simulation finished, ",
    " 个温度步，耗时 ": " temperature step(s), elapsed ",
    " 个温度步": " temperature step(s)",
    "终点 ": "End ",
    "终点温度 (K)": "Final temperature (K)",
    "是否收敛": "Converged",
    "是": "Yes",
    "否": "No",
    "⚠ 模拟未走完（可加大步长或提高起始温度）":
        "⚠ Simulation did not run to completion (increase the step or raise the "
        "start temperature)",
    "没有可导出的图": "No figure to export",
    "请先运行一次凝固模拟": "Run a solidification simulation first",

    # ================================================== ui/espei_tab.py
    "运行模式": "Run Mode",
    "模式": "Mode",
    "生成参数：线性回归直接出一套 TDB（快）\nMCMC 拟合：贝叶斯采样，需要已有的参数库（慢）\n校验数据集：只检查数据集，不训练":
        "Generate parameters: linear regression emits a TDB directly (fast)\n"
        "MCMC fitting: Bayesian sampling, needs an existing parameter set (slow)\n"
        "Check datasets: validate only, no training",
    "输入与输出": "Inputs & Outputs",
    "数据集目录": "Dataset directory",
    "目录": "Directory",
    "文件": "File",
    "输出 TDB": "Output TDB",
    "起始数据库": "Starting database",
    "选择起始 TDB": "Select starting TDB",
    "参考态": "Reference state",
    "超额模型": "Excess model",
    "岭回归 α": "Ridge α",
    "数据集标签": "Dataset tags",
    "可选：dft:-idmix,-mag;estimated-entropy:-idmix,-mag,weight=0.1":
        "Optional: dft:-idmix,-mag;estimated-entropy:-idmix,-mag,weight=0.1",
    "对应 ESPEI 的 system.tags：给带指定标签的数据集追加排除项或权重。\n"
    "留空表示不启用。也接受 JSON 对象或 .json / .yaml 文件路径。":
        "Maps to ESPEI's system.tags: append exclusions or weights to datasets "
        "carrying the given tag.\nLeave empty to disable. A JSON object or a "
        ".json / .yaml file path is also accepted.",
    "AICc 惩罚": "AICc penalty",
    "可选：LIQUID:HM=1.4,LIQUID:SM=1.4":
        "Optional: LIQUID:HM=1.4,LIQUID:SM=1.4",
    "对应 generate_parameters.aicc_penalty_factor：按相覆盖 AICc 惩罚倍数；"
    "留空表示使用 ESPEI 默认值。":
        "Maps to generate_parameters.aicc_penalty_factor: override the AICc penalty "
        "factor per phase; leave empty for the ESPEI default.",
    "MCMC 设置": "MCMC Settings",
    "迭代次数": "Iterations",
    "并行进程数": "Worker processes",
    "运行调度": "Scheduler",
    "单核串行": "Single core (serial)",
    "dask 并行": "dask (parallel)",
    "单核串行与官方教程的 scheduler: null 一致；"
    "dask 会启动后台工作进程（仅在使用多核时有优势）。":
        "Single core matches the official tutorial's scheduler: null; dask starts "
        "background worker processes (only worthwhile with multiple cores).",
    "每条链 walker 数（偶数）": "Walkers per chain (even number)",
    "初始扰动比例": "Initial perturbation scale",
    "先验": "Prior",
    "先验位置（相对参数值）": "Prior location (relative to parameter)",
    "先验尺度（相对参数值）": "Prior scale (relative to parameter)",
    "normal 先验的 loc_relative：默认 1.0，即中心在当前参数值":
        "loc_relative of the normal prior: 1.0 by default, centred on the current value",
    "normal 先验的 scale_relative：默认 1.0":
        "scale_relative of the normal prior: 1.0 by default",
    "数据权重": "Data weights",
    "运行 ESPEI": "Run ESPEI",
    "尚未运行": "Not run yet",
    "打开输出目录": "Open output directory",
    "把产出的 TDB 载入主窗口": "Load the produced TDB into the main window",
    "点击「…」选择": "Click '…' to choose ",
    "ESPEI 在这里递归搜索 *.json 数据集":
        "ESPEI searches this directory recursively for *.json datasets",
    "描述 CALPHAD 相模型的 JSON，顶层须含 components 与 phases":
        "JSON describing the CALPHAD phase models; the top level must contain "
        "components and phases",
    "ESPEI 写出的 TDB 路径": "Path of the TDB written by ESPEI",
    "MCMC 模式下的起始数据库；留空则只做 generate":
        "Starting database for MCMC; leave empty to run generate only",
    "ESPEI 目前只支持 linear（线性超额自由能）":
        "ESPEI currently supports linear only (linear excess Gibbs energy)",
    "关闭（普通最小二乘）": "Off",
    "岭回归系数；留 0 表示不做正则化":
        "Ridge coefficient; 0 means no regularization",
    "各类数据的权重；留空则用 ESPEI 默认值":
        "Weights per data type; leave empty for the ESPEI defaults",
    "ESPEI 的运行日志会出现在这里": "ESPEI's run log appears here",
    "选择 ESPEI 数据集目录": "Select ESPEI dataset directory",
    "选择 phase_models 文件": "Select the phase_models file",
    "选择起始 TDB 数据库": "Select starting TDB database",
    "ESPEI 产出的 TDB 保存位置": "Where the ESPEI TDB will be saved",
    "JSON 相模型 (*.json);;所有文件 (*)": "JSON phase models (*.json);;All files (*)",
    "热力学数据库 (*.tdb *.dat);;所有文件 (*)":
        "Thermodynamic database (*.tdb *.dat);;All files (*)",
    "热力学数据库 (*.tdb);;所有文件 (*)":
        "Thermodynamic database (*.tdb);;All files (*)",
    "开始 MCMC 拟合": "Start MCMC fitting",
    "校验数据集": "Check datasets",
    "生成参数": "Generate parameters",
    " 格式不正确": " has the wrong format",
    "数据权重 ": "Data weights ",
    "应写成「ZPF=1.0, ACR=0.5」这种「键=数值」的形式，可用键：":
        "Use 'key=value' form such as 'ZPF=1.0, ACR=0.5'. Available keys: ",
    " 不是合法键": " is not a valid key",
    "数据权重里的 ": "In the data weights, ",
    "可用键：": "Available keys: ",
    " 不是数字": " is not a number",
    " 的值 ": " value ",
    "例如 ZPF=1.0、HM=0.5": "e.g. ZPF=1.0, HM=0.5",
    "# 模式：": "# Mode: ",
    " 个 .json）": " .json file(s))",
    "# 数据集：": "# Datasets: ",
    "# 收到取消请求，将在当前步骤结束后停止…":
        "# Cancel requested — stopping after the current step…",
    " 个数据集全部合法｜耗时 ": " dataset(s) are all valid | elapsed ",
    " 个文件均合法": " file(s) are all valid",
    "ESPEI 数据集校验完成，": "ESPEI dataset check finished: ",
    "✅ 参数已生成：": "✅ Parameters generated: ",
    "｜载入数据集 ": " | datasets loaded: ",
    " 个｜耗时 ": " | elapsed ",
    "ESPEI 完成，产物：": "ESPEI finished. Output: ",
    "# 完成，产物：": "# Done. Output: ",
    "# 失败：": "# Failed: ",
    "❌ 产物已不存在：": "❌ Output no longer exists: ",
    " 载入主窗口": " loaded into the main window",
    "已把 ": "Loaded ",

    # ================================================== ui/export_dialog.py
    "导出图像": "Export Image",
    "导出数据": "Export Data",
    "格式": "Format",
    "分辨率 (DPI)": "Resolution (DPI)",
    "未选择保存位置": "No save location chosen",
    "浏览…": "Browse…",
    "PNG 位图 (*.png)": "PNG bitmap (*.png)",
    "SVG 矢量图 (*.svg)": "SVG vector image (*.svg)",
    "PDF 文档 (*.pdf)": "PDF document (*.pdf)",
    "JPG 位图 (*.jpg)": "JPG bitmap (*.jpg)",
    "CSV 文本 (*.csv)": "CSV text (*.csv)",
    "Excel 工作簿 (*.xlsx)": "Excel workbook (*.xlsx)",
    "保存图像": "Save Image",
    "保存数据": "Save Data",

    # ================================================== ui/periodic_table.py
    "元素（蓝框＝库内 · 这里勾什么，各页就只认什么 · Shift+点击框选范围）":
        "Elements (blue frame = present in the database · every page uses exactly "
        "what you tick here · Shift+click to select a range)",
    "未勾选": "Nothing selected",
    "已勾选：": "Selected: ",
    "清空": "Clear",
    "取消所有已勾选的元素": "Deselect all ticked elements",
    "库内可用": "available in the database",
    "库内不含该元素（仍可尝试选择）":
        "not in the database (you may still try selecting it)",
    " — 空位（Vacancy）：CEF 相模型亚晶格中的空位占据":
        " — Vacancy: an unoccupied site in a CEF sublattice",
    " — 电子气（Electron gas）：离子/电子相模型物种":
        " — Electron gas: a species of the ionic/electron phase model",

    # ================================================== ui/phase_list.py
    "搜索相名…": "Search phase names…",
    "反选": "Invert",
    " 子格子 · ": " sublattice(s) · ",
    "\n子格子构成：": "\nSublattice constituents: ",

    # ================================================== ui/interactive_canvas.py
    "已复位视图": "View reset",
    "已删除 tie line": "Tie line deleted",
    "已添加 tie line": "Tie line added",
    "已添加标注「": "Added label '",
    "标注「": "Label '",
    "标注 ": "Label ",
    "」已就位": "' placed",
    "已删除标注": "Label deleted",
    "三元三角投影不支持框选缩放":
        "Rubber-band zoom is not available on the ternary projection",
    "三元三角投影不支持对数坐标":
        "Logarithmic axes are not available on the ternary projection",

    # ================================================== ui/digitize_canvas.py
    "尚未导入图像\n（工具栏「导入图像」或 Ctrl+Shift+O）":
        "No image imported yet\n(toolbar 'Import Image' or Ctrl+Shift+O)",

    # ================================================== ui/digitize_tab.py
    "1. 相图类别": "1. Diagram Type",
    "类别": "Category",
    "横轴（组分）名称，会作为表格列名 X(名称)":
        "Name of the horizontal (composition) axis; used as the table column X(name)",
    "纵轴名称（一般是温度），会作为表格列名":
        "Name of the vertical axis (usually temperature); used as a table column",
    "X 轴": "X axis",
    "Y 轴": "Y axis",
    "组分": "Component",
    "X 范围": "X range",
    "Y 范围": "Y range",

    "2. 标定区域": "2. Calibrate the Area",
    "点击「开始标定」，然后按提示在图上点三个点":
        "Click 'Start calibration', then place three points as prompted",
    "开始标定": "Start calibration",
    "结束标定": "Finish calibration",
    "重新标定": "Re-calibrate",
    "① 点击坐标区**左下角**（x 最小、y 最小）":
        "① Click the **bottom-left** corner of the plot area (smallest x, smallest y)",
    "② 点击坐标区**右下角**（x 最大、y 最小）":
        "② Click the **bottom-right** corner (largest x, smallest y)",
    "③ 点击坐标区**左上角**（x 最小、y 最大）":
        "③ Click the **top-left** corner (smallest x, largest y)",
    "① 点击三角形**左下顶点**（组分 A = 1）":
        "① Click the triangle's **bottom-left vertex** (component A = 1)",
    "② 点击三角形**右下顶点**（组分 B = 1）":
        "② Click the **bottom-right vertex** (component B = 1)",
    "③ 点击三角形**上顶点**（组分 C = 1）":
        "③ Click the **top vertex** (component C = 1)",
    "已清空标定，请重新点三个点":
        "Calibration cleared — place three points again",
    "✅ 标定完成，可进入第 3 步": "✅ Calibration complete — go to step 3",
    "请先完成第 2 步标定": "Finish step 2 (calibration) first",

    "3. 去除网格线": "3. Remove Grid Lines",
    "灰度低于此值算作线条；线太浅就调高，杂点太多就调低":
        "Pixels darker than this count as ink; raise it for faint lines, lower it "
        "if noise is being picked up",
    "阈值": "Threshold",
    "去除网格线": "Remove grid lines",
    "恢复原图": "Restore image",
    "未处理": "Not processed",
    "已恢复原图": "Image restored",
    "去网格线失败：%s": "Grid-line removal failed: %s",
    "去除网格线失败：": "Grid-line removal failed: ",
    " 条（方向 ": " line(s) (angle ",
    "已去除 ": "Removed ",
    " 条网格线": " grid line(s)",
    "未发现网格线（可试着调高阈值）":
        "No grid lines found (try raising the threshold)",
    "请先导入图像": "Import an image first",

    "4. 标定相区域边界": "4. Trace Boundaries",
    "开始新区域": "Start new region",
    "完成区域（设标签）": "Finish region (set label)",
    "删最后一点": "Delete last point",
    "清空本区域": "Clear this region",
    "在边界附近单击 → 自动吸附到最近的边界像素；右键点图删除最近的点":
        "Click near a boundary → it snaps to the nearest ink pixel; right-click "
        "deletes the nearest point",
    "边界点：": "Boundary points: ",
    " 个（右键点图删除最近的点）": " (right-click to delete the nearest)",
    "至少三个点才能围成区域":
        "At least three points are needed to form a region",
    "区域标签": "Region label",
    "该区域的相（或相组合）名称：":
        "Phase (or phase assemblage) of this region:",
    "区域": "Region",
    "已保存区域 ": "Region saved ",
    "还没有标定好的区域": "No finished region yet",
    "已吸附边界点 (": "Snapped boundary point (",
    ")，共 ": "), ",
    " 点": " point(s)",
    "已删除一个边界点": "Deleted one boundary point",
    "已删除一个标定点": "Deleted one calibration point",
    "删除点失败：%s": "Could not delete the point: %s",
    "附近没找到边界（可放大视图或调高阈值）":
        "No boundary found nearby (zoom in, or raise the threshold)",
    "标定点 ": "Calibration point ",
    "/3：像素 (": "/3: pixel (",
    ") → 数据 (": ") → data (",

    "5. 生成数据": "5. Generate Data",
    "生成数据": "Generate data",
    "导出 CSV": "Export CSV",
    "成分步长": "Composition step",
    "纵轴步长": "Axis step",
    "尚未生成数据": "No data generated yet",
    "还没有可导出的数据，请先生成":
        "No data to export yet — generate it first",
    "标定不完整，无法换算数据坐标":
        "Calibration incomplete — cannot convert to data coordinates",
    "生成数字化数据失败：%s": "Digitization failed: %s",
    "生成失败：": "Generation failed: ",
    " 个区域": " region(s)",
    " 个点，": " points, ",
    "共 ": "Total ",
    " 个数据点": " data points",
    "已生成 ": "Generated ",
    "CSV 表格 (*.csv)": "CSV table (*.csv)",
    "导出数字化数据": "Export digitized data",
    "数字化页联动失败：%s": "Digitize page refresh failed: %s",
    "数字化点击处理失败：%s": "Digitize click handler failed: %s",
    "操作失败：": "Operation failed: ",
    "已导入图像 ": "Image imported ",
    "，可开始数字化（右侧「数字化相图」）":
        "; ready to digitize ('Digitize Diagram' on the right)",
    "，请从第 1 步开始": "; start from step 1",

    # ================================================== 其他零散片段
    # 拼接句的粘合剂：f-string 拼出来的整句靠这些片段兜底
    "（": " (",
    "）": ")",
    "「": "",
    "」": " ",
    "，": ", ",
    "：": ": ",
    "；": "; ",
    "。": ". ",
    "、": ", ",
}
