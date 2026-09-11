from pathlib import Path
import ast
import json
import re

p = Path('Problem1/第一问_论文正文与技术说明.md')
s = p.read_text(encoding='utf-8')
e = json.loads(Path('Problem1/problem1_lp_evidence.json').read_text(encoding='utf-8'))
assert s.count('$$') % 2 == 0
assert s.count('```') % 2 == 0
assert '\ufffd' not in s
tags = re.findall(r'\\tag\{(\d+)\}', s)
assert tags == [str(i) for i in range(1, 27)], tags
for value in [e['results']['cost_yuan'], e['results']['purchase_kwh'], e['baseline']['cost_yuan']]:
    assert f'{value:.6f}' in s
for case in e['sensitivity']:
    assert f"{case['cost_yuan']:.6f}" in s
for row in e['specified_intervals']:
    assert f"{row['purchase_kwh']:.6f}" in s
for row in e['four_hour_blocks']:
    for key in ['charge_kwh', 'discharge_kwh']:
        assert f'{row[key]:.6f}' in s
ast.parse(Path('Problem1/verify_problem1_lp.py').read_text(encoding='utf-8'))
print(json.dumps({'file': str(p), 'lines':len(s.splitlines()), 'formula_numbers':len(tags), 'json_schedule_rows':len(e['schedule']), 'numeric_tables_match':True, 'python_syntax_valid':True}, ensure_ascii=False))
