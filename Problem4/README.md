# 第四问运行说明

第四问把未来电价视为未知量。每个决策时刻只能使用此前已经发生的电价训练或构造输入，实际费用按附件4对应时段的真实电价结算。

运行顺序：

```text
python Problem4/price_forecast.py
python Problem4/Result-2/run.py
python Problem4/Result-2/replay.py
python Problem4/Result-3/run.py --variant all
python Problem4/Result-3/replay.py
node Problem4/export_results.mjs
```

- `Result-2/result4-2.xlsx`：波动电价下重新计算问题2。
- `Result-3/result4-3.xlsx`：波动电价下重新计算问题3。
- `price-results`：月度价格预测模型及预测记录。
- 两个 `results/report.json`：费用与约束检查结果。

净负荷与价格情形按同一个历史日期抽取。结果表的时段从0:00–0:10开始，数值没有因原模板表头错位而平移。
