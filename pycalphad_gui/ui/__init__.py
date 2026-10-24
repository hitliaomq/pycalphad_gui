"""GUI 层（视图组件）。

这一层只负责"长什么样、点下去触发什么信号"，不含任何计算逻辑：

- ``theme``        : 配色 / QSS / 内置图标
- ``periodic_table``: 元素周期表（库中元素高亮、点选成分）
- ``phase_list``   : 相勾选列表（排除相）
- ``diagram_view`` : 中央画布宿主（主视觉对象）
- ``interactive_canvas`` : matplotlib 画布 + 鼠标手势
- ``diagram_panel``/``condition_panel``/``property_tab``/``ht_tab`` : 右侧参数区
- ``main_window``  : QMainWindow + 左右 dock 的骨架
"""
