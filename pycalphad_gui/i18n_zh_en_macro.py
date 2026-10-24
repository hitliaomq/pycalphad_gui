"""宏命令 / 宏页面词典（中文 → 英文）。

单独成文件的原因：宏解释器与宏页贡献了 150+ 条文案，混进 ``i18n_zh_en_ui``
会让界面词典难以定位；这里按「解释器报错 / 命令回显 / 宏页界面」分组。

和另外两本词典一样，本文件只被 :mod:`i18n` 装配，不参与控件翻译扫描。
"""

MACRO_ZH_EN = {
    # ================================================== 宏页界面
    "宏命令": "Macros",
    "示例": "Examples",
    "（选择示例…）": " (choose an example…)",
    "内置的 pycalphad / scheil / ESPEI 官方示例":
        "Bundled official pycalphad / scheil / ESPEI examples",
    "打开宏…": "Open Macro…",
    "保存": "Save",
    "另存为…": "Save As…",
    "运行宏": "Run Macro",
    "停止": "Stop",
    "语法帮助": "Syntax Help",
    "未保存": "Unsaved",
    "输出日志": "Output Log",
    "结果表": "Result Table",
    "宏执行完成": "Macro finished",
    "宏执行失败": "Macro failed",
    "未保存的宏": "Unsaved Macro",
    "当前宏尚未保存，确定要放弃修改吗？":
        "This macro has unsaved changes. Discard them?",
    "宏内容为空": "The macro is empty",
    "宏内容为空，请先编写命令":
        "The macro is empty — write some commands first",
    "正在执行宏…": "Running macro…",
    "宏命令语法": "Macro Syntax",
    "保存失败": "Save Failed",
    "已保存 ": "Saved ",
    " 个结果": " result(s)",
    " 个文件": " file(s)",
    " 条命令、": " command(s), ",
    "，输出 ": ", ",
    "# 在此编写宏命令，或从上方选择示例":
        "# Write macro commands here, or pick an example above",
    "在编辑器中编写宏，或选择示例后点「运行宏」":
        "Write a macro in the editor, or pick an example and click Run Macro",
    "无法读取宏文件": "Cannot Read Macro File",
    "打开宏文件": "Open Macro File",
    "保存宏文件": "Save Macro File",
    "，点「运行宏」开始执行": "; click Run Macro to start",
    "# 收到取消请求，将在当前检查点停止…":
        "# Cancel requested; stopping at the next checkpoint…",
    "命令大小写不敏感，参数可用单双引号包住。":
        "Commands are case-insensitive; quote arguments when needed.",
    "宏文件 (*.pcm);;所有文件 (*)":
        "Macro files (*.pcm);;All files (*)",

    # ================================================== 命令回显
    "宏": "Macro",
    "已载入 ": "Loaded ",
    "｜元素数 ": " | elements: ",
    "｜相数 ": " | phases: ",
    "元素：": "Elements: ",
    "相：": "Phases: ",
    "扫描 ": "Sweep ",
    "固定条件：": "Fixed conditions: ",
    "排除后保留 ": "Remaining phases: ",
    " 个相": " phase(s)",
    "，步长 ": ", step ",
    "正在计算相图（": "Computing diagram (",
    "正在计算属性 ": "Computing property ",
    "正在模拟凝固…": "Simulating solidification…",
    "凝固模拟": "Solidification simulation",
    "凝固完成：": "Solidification done: ",
    "｜已耗尽液相": " | liquid exhausted",
    "｜液相未耗尽": " | liquid not exhausted",
    "正在运行 ESPEI…": "Running ESPEI…",
    "ESPEI 需要模式": "ESPEI needs a mode",
    "可用：GENERATE / MCMC / CHECK": "Available: GENERATE / MCMC / CHECK",
    " 完成｜数据集 ": " done | datasets: ",
    "高通量至少需要一个 SWEEP": "High-throughput needs at least one SWEEP",
    "｜失败 ": " | failed: ",
    " 点｜耗时 ": " point(s) | elapsed ",
    "已重置扫描条件、固定条件与绘图选项":
        "Reset sweeps, fixed conditions and plot options",
    "状态：尚未载入数据库": "Status: no database loaded",
    "数据库：": "Database: ",
    "相（": "Phases (",
    "扫描：": "Sweeps: ",
    "｜固定：": " | fixed: ",
    "（未选择）": " (none selected)",
    "（未设置）": " (not set)",
    "可用命令：OPEN / ELEMENTS / PHASES / EXCLUDE / SWEEP / FIXED / "
    "DIAGRAM / OPTIONS / PROPERTY / SCHEIL / EQUILIBRIUM / ESPEI / HT / "
    "EXPORT / PRINT / SET / INCLUDE / RESET / SHOW":
        "Available commands: OPEN / ELEMENTS / PHASES / EXCLUDE / SWEEP / "
        "FIXED / DIAGRAM / OPTIONS / PROPERTY / SCHEIL / EQUILIBRIUM / "
        "ESPEI / HT / EXPORT / PRINT / SET / INCLUDE / RESET / SHOW",

    # ================================================== 解释器报错（整句）
    "例如 TIELINES=OFF": "e.g. TIELINES=OFF",
    "请输入有限数值": "Enter a finite number",
    "例如 STEP 10": "e.g. STEP 10",
    "至少给出两个不同的点": "Give at least two distinct points",
    "PROPERTY 起点": "PROPERTY start",
    "PROPERTY 终点": "PROPERTY stop",
    "PROPERTY 步长": "PROPERTY step",
    "先用 SET 或 $name = 值 定义它":
        "Define it first with SET or $name = value",
    "例如 300 / 0.02 / 1e-4": "e.g. 300 / 0.02 / 1e-4",
    "例如 COMPOSITION=ZN:0.3": "e.g. COMPOSITION=ZN:0.3",
    "INCLUDE 嵌套层数过多": "INCLUDE nesting is too deep",
    "删除行尾的 \\ 或补上下一行":
        "Remove the trailing backslash or add the next line",
    "宏还没有载入数据库": "The macro has not loaded a database yet",
    "例如 OPEN database/alzn_mey.tdb": "e.g. OPEN database/alzn_mey.tdb",
    "例如 ELEMENTS AL ZN": "e.g. ELEMENTS AL ZN",
    "PHASES 需要至少一个相名": "PHASES needs at least one phase name",
    "例如 PHASES LIQUID FCC_A1": "e.g. PHASES LIQUID FCC_A1",
    "EXCLUDE 需要至少一个相名":
        "EXCLUDE needs at least one phase name",
    "例如 EXCLUDE BCC_A2": "e.g. EXCLUDE BCC_A2",
    "例如 SWEEP T 300 1000 10 或 SWEEP ZN 0 1 0.02":
        "e.g. SWEEP T 300 1000 10 or SWEEP ZN 0 1 0.02",
    " 起点": " start",
    " 终点": " stop",
    " 步长": " step",
    "FIXED 需要 变量=数值": "FIXED needs variable=value",
    "例如 FIXED T=600 或 FIXED X(ZN)=0.3":
        "e.g. FIXED T=600 or FIXED X(ZN)=0.3",
    "OPTIONS 需要至少一个 键=值":
        "OPTIONS needs at least one key=value",
    "例如 OPTIONS TIELINES=OFF GRID=ON":
        "e.g. OPTIONS TIELINES=OFF GRID=ON",
    "例如 PROPERTY GM VS ZN FROM 0 TO 1 STEP 0.02 T=600":
        "e.g. PROPERTY GM VS ZN FROM 0 TO 1 STEP 0.02 T=600",
    "凝固需要至少一个成分":
        "Solidification needs at least one composition",
    "例如 SCHEIL X(ZN)=0.3 START-T=850 STEP-T=1":
        "e.g. SCHEIL X(ZN)=0.3 START-T=850 STEP-T=1",
    "例如 SWEEP T 800 1200 100 与 SWEEP ZN 0 1 0.1":
        "e.g. SWEEP T 800 1200 100 and SWEEP ZN 0 1 0.1",
    "EXPORT 需要输出路径": "EXPORT needs an output path",
    "例如 EXPORT result.png": "e.g. EXPORT result.png",
    "例如 EXPORT FIGURE result.png / EXPORT DATA result.csv":
        "e.g. EXPORT FIGURE result.png / EXPORT DATA result.csv",
    "SET 需要 名称 值": "SET needs a name and a value",
    "例如 SET temp 850": "e.g. SET temp 850",
    "例如 INCLUDE common/load.tdb.mcm": "e.g. INCLUDE common/load.tdb.mcm",
    "先运行 DIAGRAM / PROPERTY / SCHEIL 或 ESPEI":
        "Run DIAGRAM / PROPERTY / SCHEIL or ESPEI first",
    "当前结果没有可导出的数据表":
        "The current result has no data table to export",
    "FIG-SIZE 需要 宽,高": "FIG-SIZE needs width,height",
    "例如 FIG-SIZE=9,6": "e.g. FIG-SIZE=9,6",
    "已取消：宏在检查点停止。":
        "Cancelled: the macro stopped at a checkpoint.",
    "先写一行 OPEN 数据库路径，或在界面里打开一个 TDB / DAT":
        "Add an OPEN line with the database path, or load a TDB / DAT in the window",
    "还没有选择元素": "No elements selected yet",
    "先写一行 ELEMENTS 元素1 元素2（多元素库可写 ELEMENTS *）":
        "Add an ELEMENTS line (use ELEMENTS * for every element)",
    "OPEN 需要一个数据库文件路径": "OPEN needs a database file path",
    "! 该库元素较多，请用 ELEMENTS 明确选择元素（也可写 ELEMENTS * 全选）":
        "! This database has many elements; use ELEMENTS to pick some "
        "(or ELEMENTS * for all)",
    "ELEMENTS 需要至少一个元素符号":
        "ELEMENTS needs at least one element symbol",
    "至少选择一个真实元素（VA 只是空位）":
        "Select at least one real element (VA is only a vacancy)",
    "SWEEP 需要：目标 起点 终点 步长":
        "SWEEP needs: target start stop step",
    "DIAGRAM 需要相图类型": "DIAGRAM needs a diagram type",
    "可用：BINARY / TERNARY / EQPLOT-BINARY / EQPLOT-TERNARY / STEP / ISOPLETH":
        "Available: BINARY / TERNARY / EQPLOT-BINARY / EQPLOT-TERNARY / "
        "STEP / ISOPLETH",
    "PROPERTY 需要：属性 扫描轴 起点 终点 步长":
        "PROPERTY needs: property axis start stop step",
    "INCLUDE 需要宏文件路径": "INCLUDE needs a macro file path",
    "无法读取宏文件：": "Cannot read macro file: ",
    "未知的宏命令：": "Unknown macro command: ",
    "找不到数据库文件：": "Database file not found: ",
    "解析后路径：": "Resolved path: ",
    "未知曲线来源：": "Unknown curve source: ",
    "未知凝固方法：": "Unknown solidification method: ",
    "未知 ESPEI 模式：": "Unknown ESPEI mode: ",
    "未知输出指标：": "Unknown output metric: ",
    "找不到被引用的宏文件：": "Included macro file not found: ",
    "未知绘图选项：": "Unknown plot option: ",
    "可用：": "Available: ",
    "可用：TIELINES / LABELS / GRID / AUTO-START / STEP-Y / FIG-SIZE":
        "Available: TIELINES / LABELS / GRID / AUTO-START / STEP-Y / FIG-SIZE",
    "COMPOSITION 需要 元素:分数 的形式":
        "COMPOSITION needs element:fraction",
    "高通量 / 凝固 / 属性结果可导出 CSV；相图请导出图像":
        "High-throughput / solidification / property results can be exported "
        "as CSV; export diagrams as images",
    "! 产物数据库载入失败：": "! Failed to load the output database: ",

    # ================================================== 解释器报错（片段）
    " 不能是 ": " cannot be ",
    " 的起点和终点不能相同": " start and stop must differ",
    " 有 ": " has ",
    " 个采样点，超过上限 ": " sample points, over the limit ",
    "最多 ": "At most ",
    " 行 / ": " line(s) / ",
    " 行": " line",
    " 行：": " line: ",
    " 行：变量 $": " line: variable $",
    " 没有定义": " is not defined",
    " 行：续行符后面没有内容":
        " line: nothing after the continuation backslash",
    " 层，请检查宏之间是否互相引用":
        " levels; check whether the macros include each other",
    " 需要 ON / OFF，收到 ": " expects ON / OFF, got ",
    " 需要一个数字，收到 ": " expects a number, got ",
    " 中没有相 ": " has no phase ",
    "扫描目标 ": "Sweep target ",
    "固定成分 ": "Fixed composition ",
    "成分元素 ": "Composition element ",
    "成分 ": "Composition ",
    "宏第 ": "Macro at ",
    "，也可扫 T / P": ", or sweep T / P",
    "；也可扫 T / P": "; T / P can also be swept",
    "；也可扫 T": "; T can also be swept",
    "请放大步长或缩小区间；一次算这么多点会等很久":
        "Increase the step or narrow the range; this many points will take a long time",

    # ================================================== 交互式命令面板
    "命令": "Command",
    # 英文值至少 4 个字符：反向词典会跳过更短的译文（"Run" 就翻不回"执行"）
    "执行": "Run Step",
    "重置会话": "Reset Session",
    "丢弃当前会话，下一条命令重新使用界面里的数据库与元素":
        "Discard this session; the next command starts from the database "
        "and elements in the window",
    "每行执行一条命令，状态会保留；输入 ? 查看帮助。":
        "One command per line; state is kept. Type ? for help.",
    "输入宏命令，Enter 执行；? 帮助；Tab 补全":
        "Type a macro command; Enter runs, ? shows help, Tab completes",
    "正在执行命令…": "Running command…",
    "命令执行完成｜耗时 ": "Command finished | elapsed ",
    "命令执行完成": "Command finished",
    "命令执行失败": "Command failed",
    "命令失败：": "Command failed: ",
    "未知命令：": "Unknown command: ",
    "。输入 ? 查看全部命令。": ". Type ? for all commands.",
    "# 会话已重置，下一条命令会沿用界面当前的数据库与元素":
        "# Session reset; the next command uses the database and elements "
        "in the window",
    "# 结果表已更新：": "# Result table updated: ",
    "# 结果表已更新": "# Result table updated",
    "没有匹配的候选": "No matching candidates",
    " 个候选（再按 Tab 切换）：": " candidate(s) (Tab again to cycle): ",

    # ================================================== 命令帮助
    "宏命令一览（输入 ? 显示本页，输入 命令 ? 查看详细帮助）":
        "Macro commands (type ? for this page, COMMAND ? for details)",
    "其它语法：$变量、# 或 // 注释、\\ 续行、INCLUDE 引用宏文件。"
    "命令大小写不敏感。":
        "Other syntax: $variables, # or // comments, \\ continuation, "
        "INCLUDE. Commands are case-insensitive.",
    "（别名 ": " (aliases ",
    "用法：": "Usage: ",
    "说明：": "Description: ",
    "示例：": "Examples: ",
    "载入热力学数据库": "Load a thermodynamic database",
    "路径相对当前宏文件所在目录解析，找不到时会向上查找父目录。"
    "载入后扫描条件与绘图选项会重置。":
        "Paths resolve relative to the current macro file; parent directories "
        "are also tried. Loading a database resets sweeps and plot options.",
    "选择参与计算的元素": "Select the elements used in calculations",
    "元素符号大小写不敏感；写 * 或 ALL 表示全选。":
        "Element symbols are case-insensitive; * or ALL selects every element.",
    "指定参与计算的相": "Choose the phases used in calculations",
    "写 * 或 ALL 表示全部相；相名前加 - 可从当前选择中移除。":
        "* or ALL selects every phase; prefix a phase with - to remove it "
        "from the current selection.",
    "从计算中排除相": "Exclude phases from calculations",
    "被排除的相不参与平衡计算，效果等同在 PHASES 里写 -相名。":
        "Excluded phases are left out of equilibrium calculations, like "
        "-PHASE in PHASES.",
    "设置扫描轴": "Set a sweep axis",
    "目标可以是 T、P 或元素符号；步长符号决定扫描方向，最多 5000 个采样点。":
        "The target can be T, P or an element; the step sign sets the "
        "direction, with up to 5000 points.",
    "设置固定条件": "Set fixed conditions",
    "变量可以是 T、P、N 或 X(元素)=分数，多个条件用空格分隔。":
        "Variables can be T, P, N or X(element)=fraction; separate multiple "
        "conditions with spaces.",
    "设置绘图选项": "Set plot options",
    "可用键：TIELINES、LABELS、GRID、AUTO-START、STEP-Y、FIG-SIZE。":
        "Keys: TIELINES, LABELS, GRID, AUTO-START, STEP-Y, FIG-SIZE.",
    "计算并绘制相图": "Compute and plot a phase diagram",
    "类型：BINARY、TERNARY、EQPLOT-BINARY、EQPLOT-TERNARY、STEP、ISOPLETH。"
    "计算使用 SWEEP 与 FIXED 设定的条件。":
        "Types: BINARY, TERNARY, EQPLOT-BINARY, EQPLOT-TERNARY, STEP, "
        "ISOPLETH. Uses the conditions set by SWEEP and FIXED.",
    "计算并绘制属性曲线": "Compute and plot property curves",
    "属性可以是 GM、HM、SM、CPM、NP、X(相,元素)、degree_of_ordering(相) "
    "或 sitefraction(相)；用 T=、X=、X(元素)= 固定其它条件。":
        "Properties can be GM, HM, SM, CPM, NP, X(phase,element), "
        "degree_of_ordering(phase) or sitefraction(phase); fix other "
        "conditions with T=, X= and X(element)=.",
    "执行 Scheil 凝固模拟": "Run a Scheil solidification simulation",
    "还可用 STOP=、ADAPTIVE=、LIQUID=、METHOD= 控制过程；结果可导出为 CSV。":
        "STOP=, ADAPTIVE=, LIQUID= and METHOD= control the run; results can "
        "be exported as CSV.",
    "执行平衡凝固模拟": "Run an equilibrium solidification simulation",
    "参数与 SCHEIL 相同，按平衡条件逐步降温，用来和 Scheil 结果对照。":
        "Takes the same arguments as SCHEIL and cools step by step under "
        "equilibrium, for comparison with Scheil results.",
    "运行 ESPEI 参数拟合": "Run ESPEI parameter fitting",
    "常用键：PHASE-MODELS、DATASETS、INPUT-DB、OUTPUT-DB、ITERATIONS、CORES；"
    "数据集标签用 TAGS=dft:-idmix,-mag;estimated-entropy:-idmix,-mag,weight=0.1，"
    "AICc 惩罚用 AICC=LIQUID:HM=1.4,LIQUID:SM=1.4。":
        "Common keys: PHASE-MODELS, DATASETS, INPUT-DB, OUTPUT-DB, ITERATIONS, "
        "CORES. Dataset tags: TAGS=dft:-idmix,-mag;estimated-entropy:-idmix,-mag,"
        "weight=0.1. AICc penalty: AICC=LIQUID:HM=1.4,LIQUID:SM=1.4.",
    "运行高通量平衡计算": "Run high-throughput equilibrium calculations",
    "至少需要一个 SWEEP；输出指标可用 stable_phases、gm_min、n_phases 等。":
        "At least one SWEEP is required; metrics include stable_phases, "
        "gm_min and n_phases.",
    "导出最近的图像或数据表": "Export the latest figure or data table",
    "图像支持 PNG / SVG / PDF / JPG，数据支持 CSV / XLSX；"
    "相对路径按宏文件所在目录解析。":
        "Figures support PNG / SVG / PDF / JPG and data supports CSV / "
        "XLSX; relative paths resolve against the macro directory.",
    "在输出中打印文本": "Print text to the output",
    "支持 $变量 替换，适合在宏里输出中间状态；"
    "含等号的文本请用引号包住。":
        "Supports $variables, handy for printing intermediate state; "
        "quote text that contains an equals sign.",
    "定义宏变量": "Define a macro variable",
    "也可以在行首写 $名称 = 值，之后用 $名称 引用。":
        "You can also write $name = value at the start of a line and "
        "reference it as $name.",
    "执行另一个宏文件": "Run another macro file",
    "相对路径按当前宏文件所在目录解析，最多嵌套 8 层。":
        "Relative paths resolve against the current macro directory; "
        "nesting is limited to 8 levels.",
    "重置条件与绘图选项": "Reset conditions and plot options",
    "清空扫描、固定条件与绘图选项，保留数据库、元素、相和变量。":
        "Clears sweeps, fixed conditions and plot options while keeping the "
        "database, elements, phases and variables.",
    "显示当前会话状态": "Show the current session state",
    "不带参数时显示全部状态，适合在交互式命令面板里检查当前条件。":
        "Without arguments it shows everything, which is handy for checking "
        "conditions in the command panel.",
}
