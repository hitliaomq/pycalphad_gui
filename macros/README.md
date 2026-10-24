# 宏示例库

本目录是 GUI 宏功能的示例集合，按上游项目分三类：

```
macros/
├── pycalphad/   17 个相图 / 性质 / 高通量示例
├── scheil/       2 个凝固示例
└── espei/        3 个参数拟合示例（含官方 Cu-Mg 教程数据）
```

所有宏都可以在「宏」页直接打开运行，也可以在命令行里批量跑：

```bash
python -c "from pathlib import Path; from pycalphad_gui.core.macro_engine import run_macro_text; \
p=Path('macros/pycalphad/01_binary_al_zn.pcm'); \
run_macro_text(p.read_text(encoding='utf-8-sig'), base_dir=p.parent)"
```

## 宏语法速查

- 命令大小写不敏感；`#` 或 `//` 开头为注释；行尾 `\` 续行。
- `$name = 值` 定义变量，`$name` / `${name}` 引用；`INCLUDE 其它.pcm` 按当前宏所在目录解析。
- 相对路径以**当前宏文件所在目录**为基准；`EXPORT` 的路径同样如此，目录不存在会自动创建。
- 不写 `OPEN` 时沿用界面里已载入的数据库；不写 `ELEMENTS` 时沿用界面选择。

| 命令 | 作用 | 示例 |
| --- | --- | --- |
| `OPEN` | 载入 TDB/DAT | `OPEN database/alzn_mey.tdb` |
| `ELEMENTS` | 选择组分，`*` 表示全部 | `ELEMENTS AL ZN` |
| `PHASES` / `EXCLUDE` | 选择 / 排除相 | `EXCLUDE FCC_A1` |
| `SWEEP` | 扫描轴 | `SWEEP ZN 0 1 0.02` |
| `FIXED` | 固定条件 | `FIXED T=1073.15 P=101325` |
| `OPTIONS` | 绘图选项 | `OPTIONS GRID=ON TIELINES=OFF` |
| `DIAGRAM` | 相图：`BINARY` / `TERNARY` / `EQPLOT-BINARY` / `EQPLOT-TERNARY` / `STEP` / `ISOPLETH` | `DIAGRAM BINARY` |
| `PROPERTY` | 性质曲线 | `PROPERTY NP VS T FROM 300 TO 1000 STEP 5 X(ZN)=0.3` |
| `SCHEIL` / `EQUILIBRIUM` | 凝固模拟 | `SCHEIL X(ZN)=0.3 START-T=850 STEP-T=1 LIQUID=LIQUID` |
| `ESPEI` | 参数拟合：`CHECK` / `GENERATE` / `MCMC` | `ESPEI GENERATE PHASE-MODELS=... DATASETS=...` |
| `HT` | 高通量扫描 | `HT OUTPUTS=stable_phases,gm_min PARALLEL=4` |
| `EXPORT` | 导出图像或数据 | `EXPORT FIGURE output/a.png` / `EXPORT DATA output/a.csv` |
| `PRINT` / `SHOW` / `RESET` | 输出文本 / 查看状态 / 重置条件 | `SHOW ALL` |

`PROPERTY` 的属性写法：

- `GM` / `HM` / `SM` / `CPM`（也可写 `G` / `H` / `S` / `CP`），默认按平衡相计；
- `NP`：平衡相分数；
- `X(相,元素)`：某相中该元素的摩尔分数；
- `DEGREE-OF-ORDERING(相)`：长程有序度；
- `SITEFRACTION(相)`：占位分数。

`PROPERTY` 选项：`T=`（扫成分时的温度）、`X(元素)=`（钉住其它组分）、
`SCOPE=balance|per_phase|both`、`PER-PHASE=相1,相2`。

## pycalphad 官方示例覆盖

上游示例索引：<https://pycalphad.org/docs/latest/examples/index.html>

| 官方示例 | 对应宏 | 说明 |
| --- | --- | --- |
| BinaryExamples | `01_binary_al_zn.pcm`、`16_eqplot_binary_ag_cu.pcm` | binplot 相图 + eqplot 平衡相图 |
| TernaryExamples | `02_ternary_al_cu_y.pcm`、`15_isopleth_al_cu_y.pcm`、`17_eqplot_ternary_al_cu_y.pcm` | 等温截面 / 等值线 / 三元 eqplot |
| Mapping | `03_mapping_shaded_binary.pcm` | 着色 + 相区标签开关 |
| ChargedPhases | — | **不支持**，见下方限制 |
| PhaseCompositions | `05_phase_compositions_vs_t.pcm` | 各相成分随温度变化 |
| GibbsAtConcentration | `06_gibbs_energy_per_phase.pcm` | 固定成分下逐相 Gibbs 能 |
| CementiteAnalysis | `07_cementite_heat_capacity.pcm` | 渗碳体热容（steel1.TDB） |
| EquilibriumWithOrdering | `08_ordering_ni_al.pcm`、`09_ordering_al_fe.pcm`、`10_site_fractions_ni_al.pcm` | 有序度 / 占位分数 |
| ViscosityModel | — | **不支持**，见下方限制 |
| LegacyEnergySurface | — | **不支持**，见下方限制 |
| HighThroughputCalculations | `11_high_throughput_al_zn.pcm` | 二维扫描 + CSV |
| UsingCalculationResults | `11`、`12`（导出 CSV 后处理） | 部分覆盖：宏负责算并导出，后处理交给 pandas |
| ScreeningPhaseStability | `12_screening_phase_stability.pcm` | 相稳定性筛选 |
| ReferenceStateExamples | — | **不支持**，见下方限制 |
| Metastability | `13_metastable_no_fcc.pcm` | 排除 FCC 后的亚稳相图 |
| PlotActivity | — | **不支持**，见下方限制 |
| LegacyReferenceState | — | **不支持**，见下方限制 |

另外补了两个常用相图/性质宏：

- `04_phase_fractions_vs_t.pcm`：平衡相分数 vs 温度（`NP`）；
- `14_step_diagram_al_zn.pcm`：T–x 阶跃（STEP）相图。

### 不支持的上游示例及原因

- **ChargedPhases**：带电组分需要离子物种与电中性约束；GUI 的元素/相选择
  与宏的 `ELEMENTS` 只处理中性元素。
- **ViscosityModel**：宏的 `PROPERTY` 只暴露 GM/HM/SM/CPM/NP/X/有序度/占位
  分数，未接入粘度模型。
- **LegacyEnergySurface**：依赖 pycalphad 的旧版内部能量面接口，GUI 没有
  对应命令。
- **ReferenceStateExamples / LegacyReferenceState**：需要按参考态重设
  GHSER 与参考相，宏层未暴露该 API。
- **PlotActivity**：pycalphad 0.11.2 没有活性 API（`v.ACR`、`Model.ACR`
  均不存在），无法计算。

## scheil 示例

对应 <https://github.com/pycalphad/scheil> 的 Al-Zn 凝固示例：

| 宏 | 内容 |
| --- | --- |
| `scheil/01_al_zn_scheil.pcm` | 30% Zn 合金从 850 K 的 Scheil 凝固，导出图 + CSV |
| `scheil/02_al_zn_scheil_vs_equilibrium.pcm` | 同一合金的 Scheil 与平衡凝固对比 |

CSV 列包含温度、液相分数与各相分数，可直接在 Excel / pandas 里继续处理。

## ESPEI 示例

对应 <https://espei.org/0.9.1/tutorials/cu-mg-example/cu-mg-example.html>
的完整 Cu-Mg 流程，数据与设置均取自官方教程：

| 宏 | 内容 |
| --- | --- |
| `espei/01_check_datasets.pcm` | 数据集校验（`ESPEI CHECK`） |
| `espei/02_generate_cu_mg.pcm` | 生成初始参数并写出 TDB（`ESPEI GENERATE`） |
| `espei/03_mcmc_cu_mg.pcm` | `INCLUDE` 生成步骤后跑 MCMC 不确定度量化 |

数据在 `espei/data/cu-mg/`（31 个数据集，分三层目录）：

- `phase_models.json`：LIQUID / CUMG2 / FCC_A1 / HCP_A3 / LAVES_C15 的相模型；
- `input-data/zpf/`：9 组零相分数数据；
- `input-data/activity/`：液相活度数据；
- `input-data/fixed-configuration-thermochemical/`：各相的生成焓、混合焓与熵数据。

`02_generate_cu_mg.pcm` 固定带上官方 `run_param_gen.yaml` 里的两项关键设置：
`TAGS`（dft / estimated-entropy 数据排除 `idmix`、`mag`，熵数据权重 0.1）
与 `AICC`（液相 HM/SM 惩罚乘 1.4）。去掉任何一项，生成的参数个数与数值
都会和官方教程明显不同。

`03_mcmc_cu_mg.pcm` 与官方 `run_mcmc.yaml` 一致：2000 次迭代、每条参数
4 条链、单核串行、normal 先验（loc/scale 均为 1.0）。MCMC 是随机采样，
TDB 不会逐位复现官方文件，应比较后验分布与拟合质量。Cu-Mg 单核每轮迭代
约 5~7 分钟，2000 次需要数天；只想验证链路时先把 `ITERATIONS` 改成 2。

## 运行产物

宏里的 `EXPORT` 会写到各自目录下的 `output/`（例如
`macros/pycalphad/output/`、`macros/espei/output/`）。这些文件是运行产物，
可以随时删除，不影响宏本身。
