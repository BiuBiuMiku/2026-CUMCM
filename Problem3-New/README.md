# Problem3-New

这是第三问的最新独立实现，只复用第二问在相应日期以前训练好的净负荷预测模型，不读取第二问的购电计划、SOC、费用、真实回放或全年预测结果。

运行顺序：

```text
python Problem3-New/check_inputs.py
python Problem3-New/forecast.py
python Problem3-New/schedule.py
python Problem3-New/replay.py
node Problem3-New/export_result.mjs
```

各文件作用：

- `check_inputs.py`：检查附件时间、预报发布时间和结果模板。
- `forecast.py`：加载已有模型进行推理，利用过去数据校准光伏修正系数，不训练神经网络。
- `schedule.py`：在0、6、12、18点运行随机LP并逐时段执行。
- `replay.py`：独立复核费用、供需平衡、SOC、功率和输出表。
- `export_result.mjs`：按附件5原格式生成 `results/result3.xlsx`。
- `第三问_最终技术说明.md`：可直接交给论文手使用的模型说明和结果。

正式结果统计2025年2月1日至12月31日，共334天。原始附件不会被修改。
