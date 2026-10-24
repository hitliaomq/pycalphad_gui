"""引擎 / 诊断 / 元素名词典（中文 → 英文）。

这些文案不是控件文本，而是**运行时拼出来的消息**（进度、状态栏、报错、
表格列头、图表轴题）。它们在各自产生的位置经 ``i18n.tr()`` 翻译，
或者在状态栏/对话框收口处统一翻译。

片段条目（以空格、标点开头结尾的那些）是给 ``f"已载入 {name}"`` 这类
**含变量的拼接串**兜底用的——整串不可能进词典，靠片段替换。
"""

from __future__ import annotations

from typing import Dict

CORE_ZH_EN: Dict[str, str] = {

    # ================================================== config.py
    "Gibbs 自由能 G": "Gibbs energy G",
    "焓 H": "Enthalpy H",
    "熵 S": "Entropy S",
    "定压热容 Cp": "Heat capacity Cp",
    "逐相（每个相一条曲线）": "Per phase (one curve per phase)",
    "平衡态（仅最稳定相）": "Equilibrium (most stable phase only)",
    "逐相 + 平衡态对照": "Per phase + equilibrium overlay",
    "二元 T–X 相图 (ZPFE)": "Binary T–X diagram (ZPFE)",
    "三元等温等压截面": "Ternary isothermal-isobaric section",
    "二元平衡态 (eqplot)": "Binary equilibrium (eqplot)",
    "三元平衡态 (eqplot)": "Ternary equilibrium (eqplot)",

    "稳定相组合": "Stable phases",
    "最低吉布斯自由能 (J/mol)": "Min G (J/mol)",
    "末态吉布斯自由能 (J/mol)": "Final G (J/mol)",
    "LIQUID 相分数": "LIQUID fraction",
    "共存相数": "Phase count",
    "生成参数（generate_parameters）": "Generate parameters (generate_parameters)",
    "MCMC 拟合（mcmc）": "MCMC fitting (mcmc)",
    "校验数据集（仅检查）": "Check datasets (validate only)",
    "Scheil–Gulliver（非平衡）": "Scheil–Gulliver (non-equilibrium)",
    "平衡凝固（Equilibrium）": "Equilibrium solidification",

    # ================================================== core/conditions.py
    "空": "empty",
    " 点）": " points)",
    "外部条件": "External condition",
    "组分": "Component",
    "未知相图类型：": "Unknown diagram type: ",
    "扫描维度 ": "Sweep dimension ",
    " 没有有效采样点": " has no valid sample points",
    "请检查起止值与步长": "Check the start / stop / step values",
    "」类相图要求：组分扫描 ": "-type diagrams require ",
    " 个、外部条件扫描 ": " composition sweep(s) and ",
    " 个；当前是组分 ": " external-condition sweep(s); currently ",
    " 个、外部条件 ": " and ",
    " 个。": ".",
    "请把温度或压力改为固定值，并只保留一个组分在扫描。":
        "Fix the temperature or pressure to a single value and keep exactly one "
        "composition on a sweep.",
    "请把温度设为固定值，并让两个组分同时扫描。":
        "Fix the temperature and put two compositions on sweeps.",
    " 不在数据库 ": " is not in database ",
    " 中": "",
    "可选元素：": "Available elements: ",
    "无条件": "No conditions",
    "维度 ": "Dimension ",
    " 的步长不能为 0": " cannot have a step of 0",

    # ================================================== core/database_manager.py
    "元素 ": "Element ",
    "库内可选元素：": "Elements available in the database: ",
    "尚未选择任何元素": "No elements selected yet",
    "请先在元素周期表中勾选元素":
        "Tick elements in the periodic table first",
    "数据库未解析出任何元素": "The database yielded no elements",
    "文件可能不是有效的 TDB/DAT 格式":
        "The file may not be a valid TDB/DAT database",
    "已忽略非元素组分 ": "Ignored non-element species ",
    "（空位与电荷占位不参与周期表展示）":
        " (vacancies and charge placeholders are not shown in the periodic table)",
    "库中未显式声明空位（": "Vacancies are not declared explicitly (",
    "），计算时将以隐式方式处理":
        ") — they will be handled implicitly during the calculation",
    "文件不存在：": "File not found: ",
    "解析数据库 ": "Parsing database ",
    "数据库 ": "Database ",
    " 中没有解析到任何相": " contains no phases",
    "请确认该文件是 Thermo-Calc 的 TDB 格式":
        "Make sure the file is a Thermo-Calc TDB database",
    "没有选中任何相": "No phase selected",
    "请至少启用一个相": "Enable at least one phase",
    " 在当前数据库中不存在": " does not exist in the current database",
    "相 ": "Phase ",
    "可选相：": "Available phases: ",

    # ================================================== core/diagnostics.py
    "二元相图需要「恰好 1 个变化的组分」和「恰好 1 个变化的外部条件（温度或压力）」。":
        "A binary diagram needs exactly one varying composition and exactly one "
        "varying external condition (temperature or pressure).",
    "请检查条件面板：组分扫描与温度/压力扫描各只能有一个.":
        "Check the conditions panel: exactly one composition sweep and one "
        "temperature/pressure sweep are allowed.",
    "三元等温截面需要「恰好 2 个变化的组分」，且温度、压力必须固定为单值。":
        "A ternary isothermal section needs exactly two varying compositions, with "
        "temperature and pressure fixed to single values.",
    "请把温度设为固定值，并在条件面板勾选恰好两个组分作为扫描轴.":
        "Fix the temperature and put exactly two compositions on sweep axes.",
    "自由度为不为零，条件组合在热力学上无法唯一确定体系状态。":
        "The degrees of freedom are not zero — the conditions cannot uniquely "
        "determine the state of the system.",
    "常见原因是同时给了两个组分扫描范围却让第三组分配比越界。三元体系请只让两个组分变化，第三个组分按定值固定。":
        "The usual cause is sweeping two compositions while the third goes out of "
        "range. In a ternary system only two compositions may vary; the third stays "
        "fixed.",
    "绘图坐标轴参数顺序有误。pycalphad 的相图函数中，横轴必须是组分（如 X(AL)），纵轴才能是温度等外部条件。":
        "The plot axis arguments are swapped. In pycalphad's plotting functions the "
        "horizontal axis must be a composition (e.g. X(AL)); only the vertical axis "
        "may be an external condition such as temperature.",
    "请把 X(元素) 放在横轴、T/P 放在纵轴；反之会报此错.":
        "Put X(element) on the horizontal axis and T/P on the vertical axis; "
        "swapping them triggers this error.",
    "所选元素组合在数据库中没有任何可用的相模型。":
        "No usable phase model exists for this element combination in the database.",
    "请在周期表中换一组元素，或在相列表里放宽筛选。":
        "Pick a different set of elements, or relax the filter in the phase list.",
    "过滤后没有任何相处于所选组分的活跃区间内。":
        "After filtering, no phase is active over the selected compositions.",
    "请取消部分相的排除，或换一组元素。":
        "Re-enable some of the excluded phases, or choose other elements.",
    "至少需要一个组分。": "At least one component is required.",
    "请先在周期表中选择元素。": "Select elements in the periodic table first.",
    "组分列表存在重复项。": "The component list contains duplicates.",
    "请检查选中的元素是否有大写重复。":
        "Check whether the selected elements repeat in upper case.",
    "相图类型无法自动判定：独立组分数与外部势场数不匹配。":
        "Cannot infer the diagram type: the number of independent components does "
        "not match the number of external potentials.",
    "二元图请给 1 个组分扫描 + 1 个温度/压力扫描；三元图请给 2 个组分扫描。":
        "For a binary diagram give 1 composition sweep plus 1 temperature/pressure "
        "sweep; for a ternary diagram give 2 composition sweeps.",
    "缺少 netCDF4 依赖，无法写出 netCDF 文件。":
        "The netCDF4 dependency is missing — cannot write a netCDF file.",
    "可执行 pip install netCDF4，或改用 CSV 导出。":
        "Run pip install netCDF4, or export as CSV instead.",
    "缺少 openpyxl 依赖，无法写出 Excel 文件。":
        "The openpyxl dependency is missing — cannot write an Excel file.",
    "可执行 pip install openpyxl，或改用 CSV 导出。":
        "Run pip install openpyxl, or export as CSV instead.",
    " 原始信息：": " Original message: ",
    "计算失败": "Computation failed",
    "计算失败：": "Computation failed: ",
    "计算上下文: %s\n%s": "Calculation context: %s\n%s",

    # ================================================== core/digitizer.py
    "二元相图（矩形坐标区）": "Binary diagram (rectangular plot area)",
    "三元相图（三角坐标区）": "Ternary diagram (triangular plot area)",
    "标定未完成：需要三个不共线的标定点":
        "Calibration incomplete: three non-collinear calibration points are required",
    "标定三角形退化（三点共线）":
        "The calibration triangle is degenerate (the three points are collinear)",
    "标定未完成": "Calibration incomplete",
    "标定退化，无法反算像素坐标":
        "Calibration is degenerate — cannot map back to pixel coordinates",
    "区域": "Region",
    "相标签": "Phase label",

    # ================================================== core/exporter.py
    "无法创建输出目录：": "Cannot create the output directory: ",
    "不支持的图像格式：.": "Unsupported image format: .",
    "可用格式：": "Available formats: ",
    "图像写入失败：": "Writing the image failed: ",
    "已导出图像 %s (%.1f KB)": "Image exported to %s (%.1f KB)",
    "没有可导出的曲线数据": "No curve data to export",
    "CSV 写入失败：": "Writing the CSV failed: ",
    "已导出曲线数据 %s": "Curve data exported to %s",
    "高通量结果": "High-throughput results",
    "缺少 openpyxl，无法写出 Excel 文件":
        "openpyxl is missing — cannot write an Excel file",
    "可执行：pip install openpyxl；或改用 .csv 导出":
        "Run: pip install openpyxl — or export as .csv instead",
    "Excel 写入失败：": "Writing the Excel file failed: ",
    "不支持的数据格式：.": "Unsupported data format: .",
    "已导出数据 %s": "Data exported to %s",

    # ================================================== core/high_throughput.py
    "最低G (J/mol)": "Lowest G (J/mol)",
    "末态G (J/mol)": "Final-state G (J/mol)",
    "液相分数": "Liquid fraction",
    "高通量任务至少需要指定一个扫描维度":
        "A high-throughput job needs at least one sweep dimension",
    " 没有采样点": " has no sample points",
    "高通量点 ": "High-throughput point ",
    "高通量": "High throughput",
    "已完成 ": "Finished ",
    "高通量计算": "High-throughput computation",

    # ================================================== core/plot_engine.py
    "温度 T (K)": "Temperature T (K)",
    "压强 P (Pa)": "Pressure P (Pa)",
    "总摩尔数 N (mol)": "Total moles N (mol)",
    "摩尔分数 X(": "Mole fraction X(",
    "网格法：正在求解 ": "Grid method: solving ",
    " 平衡…": " equilibria…",
    "网格法没有求得任何有效平衡":
        "The grid method found no valid equilibrium",
    "请检查固定温度是否在数据库有效区间内，或勾选更多相":
        "Check that the fixed temperature is inside the database's valid range, or "
        "tick more phases",
    "相": "phase",
    "网格法无法在平衡结果中找到扫描组分的成分数据":
        "The grid method could not find composition data for the sweep axis in the "
        "equilibrium result",
    "扫描轴 ": "Sweep axis ",
    "，结果成分维度：": "; resulting composition dimensions: ",
    "正在计算二元 ZPFE 相图…": "Computing the binary ZPFE diagram…",
    "Step 图（单轴步进）": "Step plot (single-axis stepping)",
    "Isopleth（垂直截面）": "Isopleth (vertical section)",
    "正在计算 Step 图（单轴步进）…": "Computing step plot (single-axis stepping)…",
    "正在绘制 Step 图…": "Plotting the step diagram…",
    "正在计算 Isopleth 垂直截面…": "Computing isopleth (vertical section)…",
    "正在绘制 Isopleth…": "Plotting the isopleth…",
    "相分数": "Phase fraction",
    "Step 图只需要 1 个扫描维度（温度、压强或成分）": "Step plot needs exactly one sweep axis (temperature, pressure or composition)",
    "请删除多余扫描维度只留一个；其余量在「固定条件」里固定": "Remove the extra sweeps and keep one; fix the rest under Fixed conditions",
    "Isopleth 垂直截面要求：组分扫描 1 个 + 温度扫描 1 个": "Isopleth requires 1 composition sweep + 1 temperature sweep",
    "再在「固定条件」里添加固定成分，钉住剩余自由度": "Also add fixed compositions under Fixed conditions to pin the remaining degrees of freedom",
    "Isopleth 至少要固定 1 个成分（多出的自由度必须钉住）": "Isopleth needs at least one fixed composition (the remaining degree of freedom must be pinned)",
    "请在「固定条件」里点「+ 添加固定成分」，填入元素与摩尔分数": "Click '+ Add fixed composition' under Fixed conditions and enter the element and mole fraction",
    "目标相在此区间可能始终不稳定：请调整扫描范围 / 固定条件，或换一个目标相": "The target phase may never be stable in this range: adjust the sweep range / fixed conditions, or pick another target phase",
    "✅ Scheil 凝固曲线（": "✅ Scheil solidification curve (",
    "二元映射填色失败，改用 binplot": "Binary shaded mapping failed, falling back to binplot",
    "ESPEI 拟合对比图": "ESPEI fit comparison plot",
    "ESPEI 拟合对比｜": "ESPEI fit comparison | ",
    "# 对比图生成失败（不影响拟合产物）：": "# Fit comparison plot failed (results unaffected): ",
    "对比图": "comparison plot",
    " 的对比图：": " comparison plot: ",
    "对比图": "comparison plot",
    "数据集没有可用的温度条件": "No usable temperature conditions in the datasets",
    "正在绘制拟合对比图…": "Plotting the fit comparison…",
    "ESPEI 对比图 ": "ESPEI comparison plot ",
    "# 跳过 ": "# Skipped ",
    "正在计算三元等温等压截面…":
        "Computing the ternary isothermal-isobaric section…",
    "三元等温截面需要两个组分扫描轴":
        "A ternary isothermal section needs two composition sweep axes",
    "当前只有 ": "currently only ",
    "三元等温截面至少需要三个元素：两个作扫描轴，第三个决定截面位置":
        "A ternary isothermal section needs at least three elements: two as sweep "
        "axes and a third fixing the section",
    "——请回周期表补选第三个元素":
        " — go back to the periodic table and tick a third element",
    "当前勾选的真元素只有 ": "The only real elements ticked are ",
    "三元映射算法失败，改用网格法":
        "The ternary mapping algorithm failed; falling back to the grid method",
    "正在绘制三元相图…": "Plotting the ternary diagram…",
    "映射未收敛，改用网格法求解等温截面…":
        "Mapping did not converge; solving the isothermal section with the grid "
        "method…",
    "（网格法）": " (grid method)",
    "正在求解平衡态…": "Solving the equilibrium…",
    "正在绘制相区…": "Plotting phase regions…",
    "三元平衡态需要两个组分扫描轴":
        "Ternary equilibrium needs two composition sweep axes",
    "完成": "Done",
    "不支持的相图类型：": "Unsupported diagram type: ",
    " 相图": " diagram",
    "绘制 ": "Plotting ",
    "相图": "diagram",
    "失败：": "failed: ",
    "可选组分：": "Available components: ",
    "扫描点上存在非法值": "Illegal values on the sweep points",
    "正在计算平衡态 ": "Computing equilibrium ",
    " 个值，与 ": " values, but ",
    " 返回了 ": " returned ",
    "属性 ": "Property ",
    " 个扫描点对不上": " sweep points — mismatch",
    "请缩小扫描范围或减少采样点步长":
        "Shrink the sweep range or increase the step size",
    " 在扫描范围内没有有限值": " has no finite value over the sweep range",
    "常见原因：固定温度超出数据库有效区间、相选择不当，请调整固定温度 / 固定组分或勾选更多相":
        "Common causes: the fixed temperature lies outside the database's valid "
        "range, or the phase selection is unsuitable — adjust the fixed temperature "
        "/ composition, or tick more phases",
    "平衡态": "equilibrium",
    " 在扫描范围内没有可用的有限值":
        " has no usable finite value over the sweep range",
    "常见于温度或成分超出了数据库的有效区间，请调整固定温度 / 固定组分，或在右侧勾选更多相":
        "Usually the temperature or composition is outside the database's valid "
        "range — adjust the fixed temperature / composition, or tick more phases on "
        "the right",
    "正在绘制属性曲线…": "Plotting property curves…",
    "扫描 ": "Sweep ",
    "固定 X(": "Fixed X(",
    "固定 T = ": "Fixed T = ",
    "计算属性 ": "Computing property ",
    "属性计算 ": "Property computation ",
    "（返回 ": " (returned ",
    " 个值）": " value(s))",
    "（无有限值）": " (no finite value)",

    # ================================================== core/scheil_engine.py
    "不支持的凝固方法：": "Unsupported solidification method: ",
    "可选：": "Available: ",
    "否则体系没有确定的成分点":
        "otherwise the system has no well-defined composition point",
    "请至少设置一个元素成分": "Set at least one element composition",
    "成分总和必须大于 0": "The composition sum must be greater than 0",
    "请检查摩尔分数是否填反了":
        "Check whether the mole fractions were entered the wrong way round",
    "请填写至少一个元素的摩尔分数":
        "Fill in the mole fraction of at least one element",
    "成分点为空时 scheil 无法构造条件":
        "scheil cannot build conditions from an empty composition point",
    "已填组分的摩尔分数之和必须小于 1":
        "The sum of the filled mole fractions must be less than 1",
    "当前已填 ": "filled so far: ",
    "）不能为负": ") must not be negative",
    "，剩余量（溶剂 ": "; the remainder (solvent ",
    "相模型与组分不匹配": "Phase models do not match the components",
    " 不在启用的相列表里": " is not among the enabled phases",
    "液相候选 ": "Liquid candidates: ",
    "当前启用的相：": "Currently enabled phases: ",
    "温度 (K)": "Temperature (K)",
    "固相分数": "Solid fraction",
    "液相分数": "Liquid fraction",
    " 分数": " fraction",
    "固相总量": "Total solid",
    "温度 T (K)": "Temperature T (K)",
    "分数": "Fraction",
    "正在准备相模型与初始态…": "Preparing phase models and the initial state…",
    " 凝固模拟收尾": " solidification simulation, wrapping up",
    "凝固模拟没有跑到底：在到达终点前就用尽了温度步长":
        "The solidification simulation did not run to the end: the temperature steps "
        "were exhausted before reaching the end point",
    "请把「液相相名」改成本库真实的液相（如 ":
        "Set 'Liquid phase name' to a real liquid phase of this database (e.g. ",
    "），或把起始温度提高、加大温度步长。原始信息：":
        "), or raise the start temperature / increase the temperature step. "
        "Original message: ",
    " 凝固模拟求解": " solidification simulation, solving",
    "凝固模拟在求解某一步时数值发散":
        "The solidification simulation diverged at one of the steps",
    "常见于起始温度太低（不是单一液相区）或温度步长过大，建议把起始温度提到 ":
        "Usually the start temperature is too low (not inside the single-liquid "
        "region) or the temperature step is too large. Try raising the start "
        "temperature to about ",
    " K 左右再试。原始信息：": " K. Original message: ",
    " 凝固模拟": " solidification simulation",
    "正在汇总结果…": "Summarising results…",
    "凝固 — ": "Solidification — ",
    "平衡": "equilibrium",
    "平衡凝固": "Equilibrium solidification",
    "方法": "Method",
    "成分点": "Composition point",
    "，其余为 ": ", remainder ",
    "起点温度 (K)": "Start temperature (K)",
    "终点温度 (K)": "Final temperature (K)",
    "步数": "Steps",
    "最终固相分数": "Final solid fraction",
    "剩余液相": "Remaining liquid",
    "析出相": "Precipitated phases",
    "是否收敛": "Converged",
    "是": "Yes",
    "否（未走完，可加大温度步长）":
        "No (did not finish — increase the temperature step)",
    "没有任何一步求解收敛": "Not a single step converged",
    "请检查起始温度是否落在单一液相区、所选元素能否让液相激活":
        "Check that the start temperature lies in the single-liquid region and that "
        "the selected elements activate the liquid",
    "数据集类型无法识别": "Unrecognised dataset type",
    "这与凝固模拟无关，可能是相名写错导致相模型无法匹配":
        "This is unrelated to the solidification run — a misspelled phase name may "
        "have broken phase-model matching",
    "请检查是否启用了不含所选元素的相":
        "Check whether you enabled phases that contain none of the selected elements",
    "所选组分下没有任何相处于活跃状态":
        "No phase is active at the selected components",
    "请换一组元素或放宽相的启用范围":
        "Choose other elements, or widen the range of enabled phases",
    "凝固模拟失败：": "Solidification simulation failed: ",
    "。原始信息：": ". Original message: ",

    # ================================================== core/espei_engine.py
    "ESPEI 用 *.json 数据集训练，目录里至少要有一个文件":
        "ESPEI trains on *.json datasets; the directory needs at least one file",
    "请指定数据集目录": "Specify the dataset directory",
    "ESPEI 需要一个描述 CALPHAD 相模型的 .json":
        "ESPEI needs a .json file describing the CALPHAD phase models",
    "请指定 phase_models 文件": "Specify the phase_models file",
    "里面应包含若干 ESPEI 格式的 .json 数据集":
        "it should contain several ESPEI-format .json datasets",
    "找不到 phase_models 文件：": "phase_models file not found: ",
    "完整路径：": "Full path: ",
    "找不到数据集目录：": "Dataset directory not found: ",
    "ESPEI 在数据集目录里递归搜索 *.json":
        "ESPEI searches the dataset directory recursively for *.json",
    "MCMC 需要一个起始数据库": "MCMC needs a starting database",
    "请填写 input_db（上一轮 generate 产出的 TDB）":
        "Fill in input_db (the TDB produced by a previous generate run)",
    "找不到起始数据库：": "Starting database not found: ",
    "MCMC 迭代次数必须大于 0": "MCMC iterations must be greater than 0",
    "典型值 100 ~ 20000": "Typical range: 100 – 20000",
    "phase_models 不是合法 JSON：": "phase_models is not valid JSON: ",
    " 列：": " column: ",
    " 行第 ": " row, column ",
    "第 ": "at ",
    "无法读取 ": "Cannot read ",
    "phase_models 顶层必须是对象": "The top level of phase_models must be an object",
    "实际读到 ": "actually got ",
    " 个数据集，正在逐个校验…": " dataset(s), validating one by one…",
    "发现 ": "Found ",
    " 个数据集": " dataset(s)",
    "已校验 ": "Validated ",
    " 个数据集不合法": " dataset(s) are invalid",
    "校验 ESPEI 运行参数": "Validating the ESPEI run parameters",
    "generate_parameters 需要显式给出 fitting_description":
        "generate_parameters requires an explicit fitting_description",
    "多余自由能模型目前只支持 linear":
        "Only the linear excess Gibbs energy model is supported at present",
    "参考态只支持 SGTE91 / SR2016":
        "Only the SGTE91 / SR2016 reference states are supported",
    "chains_per_parameter 必须是 ≥2 的偶数":
        "chains_per_parameter must be an even number ≥ 2",
    "restart_trace 需要配合 mcmc.input_db 一起填":
        "restart_trace must be used together with mcmc.input_db",
    "MCMC 的 iterations 必须是 ≥0 的整数":
        "MCMC iterations must be an integer ≥ 0",
    "system.datasets 必须指向存放 .json 数据集的目录":
        "system.datasets must point to a directory holding .json datasets",
    "system.phase_models 必须指向一个 .json 相模型文件":
        "system.phase_models must point to a .json phase-model file",
    "output.output_db 是 ESPEI 写出 TDB 的路径":
        "output.output_db is the path where ESPEI writes the TDB",
    "ESPEI 运行参数不合法，请检查面板填写":
        "Invalid ESPEI run parameters — check the panel entries",
    "正在载入数据集并训练…": "Loading datasets and training…",
    "ESPEI 没有产出预期的数据库：": "ESPEI did not produce the expected database: ",
    "请检查输出路径是否被占用：": "Check whether the output path is locked: ",
    "数据集目录里没有找到任何 .json 数据集":
        "No .json dataset found in the dataset directory",
    "ESPEI 在数据目录中递归搜索 *.json，请确认选的是目录而不是单个文件":
        "ESPEI searches the dataset directory recursively for *.json — make sure you "
        "selected a directory, not a single file",
    "数据集无法识别类型": "Cannot determine the dataset type",
    "数据集需要填写 output 键（ZPF / ACR / HM / SM / CPM）":
        "Datasets need an output key (ZPF / ACR / HM / SM / CPM)",
    "MCMC 的 chains_per_parameter 必须是偶数且不小于 2":
        "MCMC chains_per_parameter must be even and at least 2",
    "它与每条链的参数个数有关：偶数 walks 才跑得动 emcee":
        "It relates to the number of parameters per chain: emcee only runs with an "
        "even number of walkers",
    "MCMC 没有恢复出最优参数": "MCMC did not recover optimal parameters",
    "数据集标签不是合法 JSON": "Dataset tags are not valid JSON",
    "数据集标签必须是「标签名 → 设置」的对象":
        "Dataset tags must be an object of 'tag → settings'",
    '例如 {"dft": {"excluded_model_contributions": ["idmix"]}}':
        'e.g. {"dft": {"excluded_model_contributions": ["idmix"]}}',
    "读取 YAML 标签需要 PyYAML": "Reading YAML tags requires PyYAML",
    "标签文件 ": "Tag file ",
    " 顶层必须是对象": " must have an object at the top level",
    "实际不是": "it is not",
    "数据集标签 ": "Dataset tag ",
    "写成「标签名:-排除项,weight=数值」，例如 dft:-idmix,-mag":
        "Use 'tag:-excluded,weight=value', e.g. dft:-idmix,-mag",
    " 里的 ": " contains ",
    " 无法识别": " is not recognized",
    "排除项写成 -idmix，其余设置写成 weight=0.1":
        "Write exclusions as -idmix and other settings as weight=0.1",
    "AICc 惩罚不是合法 JSON": "The AICc penalty is not valid JSON",
    "AICc 惩罚必须是「相名 → {数据类: 倍数}」的对象":
        "The AICc penalty must be an object of 'phase → {data type: factor}'",
    '例如 {"LIQUID": {"HM": 1.4, "SM": 1.4}}':
        'e.g. {"LIQUID": {"HM": 1.4, "SM": 1.4}}',
    "AICc 惩罚 ": "AICc penalty ",
    "写成「相名:数据类=倍数」，例如 LIQUID:HM=1.4":
        "Use 'phase:data-type=factor', e.g. LIQUID:HM=1.4",
    " 的倍数不是数字": " factor is not a number",
    "例如 LIQUID:HM=1.4": "e.g. LIQUID:HM=1.4",
    "迭代次数太少或先验设置不当，可增大迭代次数":
        "Too few iterations, or the prior is unsuitable — increase the iteration "
        "count",
    "MCMC 迭代过程中没有任何一步收敛":
        "No step of the MCMC run converged",
    "起始数据库可能缺少待拟合的相模型":
        "The starting database may lack the phase models to be fitted",
    "缺少依赖": "Missing dependency",
    "ESPEI 需要 dask / distributed / emcee / cerberus，可执行 pip install -e .[espei]":
        "ESPEI needs dask / distributed / emcee / cerberus — run "
        "pip install -e .[espei]",
    " 失败：": " failed: ",
    "写出数据库 ": "Writing database ",
    "写出数据库失败：": "Writing the database failed: ",
    "请确认目录可写。原始信息：": "Make sure the directory is writable. Original message: ",

    # ================================================== workers/base_worker.py
    "任务已取消": "Task cancelled",
    "后台任务": "Background task",
    "计算": "Calculation",

    # ================================================== 元素名（elements.py）
    # 仅用于周期表格子的 tooltip（如 "26. Fe 铁"）。单字条目不会被当作
    # 片段替换，因此在周期表里由 retranslate() 显式翻译。
    "氢": "Hydrogen", "氦": "Helium", "锂": "Lithium", "铍": "Beryllium",
    "硼": "Boron", "碳": "Carbon", "氮": "Nitrogen", "氧": "Oxygen",
    "氟": "Fluorine", "氖": "Neon", "钠": "Sodium", "镁": "Magnesium",
    "铝": "Aluminium", "硅": "Silicon", "磷": "Phosphorus", "硫": "Sulfur",
    "氯": "Chlorine", "氩": "Argon", "钾": "Potassium", "钙": "Calcium",
    "钪": "Scandium", "钛": "Titanium", "钒": "Vanadium", "铬": "Chromium",
    "锰": "Manganese", "铁": "Iron", "钴": "Cobalt", "镍": "Nickel",
    "铜": "Copper", "锌": "Zinc", "镓": "Gallium", "锗": "Germanium",
    "砷": "Arsenic", "硒": "Selenium", "溴": "Bromine", "氪": "Krypton",
    "铷": "Rubidium", "锶": "Strontium", "钇": "Yttrium", "锆": "Zirconium",
    "铌": "Niobium", "钼": "Molybdenum", "锝": "Technetium", "钌": "Ruthenium",
    "铑": "Rhodium", "钯": "Palladium", "银": "Silver", "镉": "Cadmium",
    "铟": "Indium", "锡": "Tin", "锑": "Antimony", "碲": "Tellurium",
    "碘": "Iodine", "氙": "Xenon", "铯": "Caesium", "钡": "Barium",
    "铪": "Hafnium", "钽": "Tantalum", "钨": "Tungsten", "铼": "Rhenium",
    "锇": "Osmium", "铱": "Iridium", "铂": "Platinum", "金": "Gold",
    "汞": "Mercury", "铊": "Thallium", "铅": "Lead", "铋": "Bismuth",
    "钋": "Polonium", "砹": "Astatine", "氡": "Radon", "钫": "Francium",
    "镭": "Radium", "钕": "Neodymium", "铈": "Cerium", "镧": "Lanthanum",
    "镨": "Praseodymium", "钆": "Gadolinium", "钐": "Samarium",
    "钷": "Promethium", "铕": "Europium", "钬": "Holmium", "铒": "Erbium",
    "铽": "Terbium", "镝": "Dysprosium", "铥": "Thulium", "镥": "Lutetium",
    "镱": "Ytterbium", "钍": "Thorium", "铀": "Uranium", "锕": "Actinium",
    "镤": "Protactinium", "钚": "Plutonium", "锔": "Curium",
    "镅": "Americium", "镎": "Neptunium", "锎": "Californium",
    "锫": "Berkelium", "锿": "Einsteinium", "镄": "Fermium",
    "钔": "Mendelevium", "铹": "Lawrencium", "锘": "Nobelium",
}
