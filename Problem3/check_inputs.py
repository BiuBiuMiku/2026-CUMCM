"""Read-only source audit: explicit timestamps, maturity masks, template intervals.

Run from any directory with Python and NumPy. No source workbook is modified.
"""
from datetime import datetime, timedelta
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Problem2'))
from common import read_xlsx, sha256


def forecast_records():
    rows = read_xlsx(ROOT / 'C题/附件/附件3.xlsx')['Sheet1']
    assert rows[0][2:] == [f'预报{h}小时' for h in range(1, 25)]
    day = None
    records = []
    for excel_row, row in enumerate(rows[1:], 2):
        if row[0] not in ('', None):
            day = datetime.strptime(row[0], '%Y-%m-%d')
        assert day is not None
        hour, minute = map(int, row[1].split(':'))
        assert hour in (0, 6, 12, 18) and minute == 0
        issued = day + timedelta(hours=hour)
        for h, power in enumerate(row[2:], 1):
            assert np.isfinite(power) and power >= 0
            records.append((issued, issued + timedelta(hours=h), h, power, excel_row))
    assert len(records) == 365 * 4 * 24
    assert len({(r[0], r[1]) for r in records}) == len(records)
    return records


def observed_pv():
    rows = read_xlsx(ROOT / 'C题/附件/附件2.xlsx')['光伏发电实际功率']
    assert np.allclose(rows[0][1:144], np.arange(1, 144) / 144)
    assert rows[0][144] == '0:00+1'
    origin = datetime(1899, 12, 30)
    result = {}
    for row in rows[1:]:
        midnight = origin + timedelta(days=row[0])
        for i, power in enumerate(row[1:], 1):
            stamp = midnight + timedelta(minutes=10*i)
            assert stamp not in result
            result[stamp] = power
    assert len(result) == 365*144
    return result


def settled_records(records, actual, cutoff):
    """Conservative boundary: target strictly precedes model fit/decision time."""
    return [r for r in records if r[0] < cutoff and r[1] < cutoff and r[1] in actual]


def settled_paths(records, actual, cutoff):
    """A whole 24-hour path is eligible only after every label is observed.

    This checks maturity only; callers must separately require archived OOS
    predictions made by models fitted before each historical issue time.
    """
    issues = sorted({r[0] for r in records})
    return [r for r in issues if r + timedelta(hours=24) < cutoff
            and all(r + timedelta(hours=h) in actual for h in range(1,25))]


def interval_minutes(label):
    left, right = label.split('-')
    def minute(text):
        next_day = text.endswith('+1')
        if next_day:
            text = text[:-2]
        hour, minute = map(int, text.split(':'))
        return 60*hour + minute + 1440*next_day
    start, end = minute(left), minute(right)
    # Final '+1' may qualify the whole interval: 0:00-0:10+1.
    if end - start > 1440:
        start += 1440
    return start, end


def main():
    records, actual = forecast_records(), observed_pv()
    cutoff = datetime(2025, 2, 1)
    mature = settled_records(records, actual, cutoff)
    assert all(r[1] < cutoff for r in mature)
    jan31_18 = [r for r in records if r[0] == datetime(2025,1,31,18)]
    assert sum(r in mature for r in jan31_18) == 5
    assert datetime(2025,1,31,18) not in settled_paths(records,actual,cutoff)
    # A same target has independent forecast vintages.
    same_target = [r for r in records if r[1] == datetime(2025,1,1,12)]
    assert [(r[0].hour,r[2]) for r in same_target] == [(0,12),(6,6)]
    missing = [r for r in records if r[1] not in actual]
    assert len(missing) == 36
    assert all(r[1] > datetime(2026,1,1) for r in missing)
    print('Forecast cells:',len(records), 'matched actuals:',len(records)-len(missing),
          'future targets without truth:',len(missing))
    print('Jan31 18:00 row: Feb1 00:00 fit accepts leads 1..5 (strict cutoff).')
    print('Jan31 18:00 full path is NOT eligible at Feb1 00:00.')
    print('Forecast target range:',records[0][1],records[-1][1])
    template = read_xlsx(ROOT / 'C题/附件/附件5/result3.xlsx')
    for sheet in ['计划购电量','调整购电量']:
        intervals = [interval_minutes(s) for s in template[sheet][0][1:145]]
        assert len(intervals) == 144
        assert all(end-start == 10 for start,end in intervals)
        assert all(a[1] == b[0] for a,b in zip(intervals,intervals[1:]))
        assert intervals[0] == (10,20) and intervals[-1] == (1440,1450)
        print(sheet, 'template window:',intervals[0][0], 'to', intervals[-1][1],
              'minutes after row date midnight')
    for rel in ['附件1.xlsx','附件2.xlsx','附件3.xlsx','附件5/result3.xlsx']:
        print('SHA256', rel, sha256(ROOT/'C题/附件'/rel))


if __name__ == '__main__':
    main()
