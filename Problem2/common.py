"""Shared data/feature definitions. Does not import torch or scipy."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import hashlib
import json
import posixpath
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'C题').is_dir())
HERE = Path(__file__).resolve().parent
OUT = HERE / 'results'
DT = 1 / 6
STEPS = 144
E_MIN, E_MAX, E_INITIAL, ETA, U = 1200.0, 10800.0, 6000.0, 0.9, 5000 / 6
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def read_xlsx(path: Path) -> dict[str, list[list]]:
    """Read only this task's ordinary XLSX cell values, using the standard library.

    Styles are not interpreted. Dates remain Excel serials; formulas are rejected.
    This avoids requiring a spreadsheet writer or modifying any original workbook.
    """
    with zipfile.ZipFile(path) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(si.itertext()) for si in root.findall('m:si', NS)]
        relationships = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        rels = {r.attrib['Id']: r.attrib['Target'] for r in relationships}
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        result = {}
        for sheet in book.findall('m:sheets/m:sheet', NS):
            rid = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
            target = rels[rid]
            name = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            root = ET.fromstring(archive.read(name))
            cells = {}
            for cell in root.findall('m:sheetData/m:row/m:c', NS):
                if cell.find('m:f', NS) is not None:
                    raise ValueError(f'Unexpected formula in raw data: {sheet.attrib["name"]} {cell.attrib["r"]}')
                address = cell.attrib['r']
                letters = ''.join(c for c in address if c.isalpha())
                row = int(''.join(c for c in address if c.isdigit())) - 1
                col = 0
                for char in letters:
                    col = col * 26 + ord(char.upper()) - 64
                raw = cell.find('m:v', NS)
                typ = cell.attrib.get('t')
                if typ == 'inlineStr':
                    value = ''.join(cell.find('m:is', NS).itertext())
                elif raw is None or raw.text is None:
                    continue
                elif typ == 's':
                    value = strings[int(raw.text)]
                elif typ in ('str', 'e'):
                    value = raw.text
                else:
                    value = float(raw.text)
                cells[(row, col - 1)] = value
            nrows = max(r for r, _ in cells) + 1
            ncols = max(c for _, c in cells) + 1
            matrix = [[None] * ncols for _ in range(nrows)]
            for (r, c), v in cells.items():
                matrix[r][c] = v
            result[sheet.attrib['name']] = matrix
        return result


@dataclass
class Data:
    dates: np.ndarray
    load_kw: np.ndarray
    pv_kw: np.ndarray
    price: np.ndarray
    sources: dict

    @property
    def net_kw(self):
        return self.load_kw - self.pv_kw


def load_data() -> Data:
    p1 = ROOT / 'C题' / '附件' / '附件1.xlsx'
    p2 = ROOT / 'C题' / '附件' / '附件2.xlsx'
    first = list(read_xlsx(p1).values())[0]
    second = read_xlsx(p2)
    load = second['小区负载']
    pv = second['光伏发电实际功率']
    assert len(load) == len(pv) == 366
    excel_origin = datetime(1899, 12, 30)
    dates = np.array([(excel_origin + timedelta(days=row[0])).date().isoformat() for row in load[1:]])
    pv_dates = [(excel_origin + timedelta(days=row[0])).date().isoformat() for row in pv[1:]]
    assert dates.tolist() == pv_dates
    expected = [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(365)]
    assert dates.tolist() == expected
    a = np.asarray([r[1:] for r in load[1:]], dtype=float)
    b = np.asarray([r[1:] for r in pv[1:]], dtype=float)
    price = np.asarray([r[1] for r in first[1:]], dtype=float)
    assert a.shape == b.shape == (365, 144) and price.shape == (144,)
    assert np.isfinite(a).all() and np.isfinite(b).all() and np.isfinite(price).all()
    assert a.min() >= 0 and b.min() >= 0 and price.min() > 0
    # Match 00:10,...,23:50 numeric Excel times; final label denotes next midnight.
    assert np.allclose(np.asarray(load[0][1:144],float), np.arange(1,144)/144)
    assert load[0][144] == pv[0][144] == '0:00+1'
    return Data(dates, a, b, price, {'attachment1_sha256': sha256(p1), 'attachment2_sha256': sha256(p2)})


FEATURE_NAMES = [
    'slot_sin','slot_cos','slot_sin2','slot_cos2','weekday_sin','weekday_cos',
    'year_sin','year_cos','day_ahead',
    'load_last1','pv_last1','load_last2','pv_last2','load_last7','pv_last7',
    'load_last14','pv_last14','load_mean3','pv_mean3','load_mean7','pv_mean7',
    'load_std7','pv_std7','load_same_weekday','pv_same_weekday',
    'baseline_net','net_last1_mean_day','net_last1_std_day',
    'net_mean7_mean_day','net_mean7_std_day',
]


def features(history_load, history_pv, issue_date: date, ahead: int):
    """Input arrays MUST end before the issue date. No target truth accepted."""
    assert ahead in (0,1) and history_load.shape == history_pv.shape
    length = len(history_load)
    target = issue_date + timedelta(days=ahead)
    zeros = np.zeros(144)
    def lag(k, arr):
        return arr[-min(k,length)] if length else zeros
    def avg(k, arr):
        return arr[-k:].mean(axis=0) if length else zeros
    def std(k, arr):
        return arr[-k:].std(axis=0) if length else zeros
    same_ids = [i for i in range(max(0,length-28),length)
                if (issue_date-timedelta(days=length-i)).weekday() == target.weekday()]
    same_l = history_load[same_ids].mean(0) if same_ids else avg(7, history_load)
    same_p = history_pv[same_ids].mean(0) if same_ids else avg(7, history_pv)
    base = 0.5*(same_l-same_p) + 0.5*(avg(3,history_load)-avg(3,history_pv))
    angle = 2*np.pi*np.arange(144)/144
    year_angle = 2*np.pi*(target.timetuple().tm_yday-1)/365.25
    net_last = lag(1,history_load)-lag(1,history_pv)
    net_mean7 = avg(7,history_load)-avg(7,history_pv)
    const = lambda v: np.full(144,v)
    cols = [np.sin(angle),np.cos(angle),np.sin(2*angle),np.cos(2*angle),
            const(np.sin(2*np.pi*target.weekday()/7)),const(np.cos(2*np.pi*target.weekday()/7)),
            const(np.sin(year_angle)),const(np.cos(year_angle)),const(ahead)]
    for k in [1,2,7,14]:
        cols += [lag(k,history_load),lag(k,history_pv)]
    cols += [avg(3,history_load),avg(3,history_pv),avg(7,history_load),avg(7,history_pv),
             std(7,history_load),std(7,history_pv),same_l,same_p,base,
             const(net_last.mean()),const(net_last.std()),const(net_mean7.mean()),const(net_mean7.std())]
    result = np.column_stack(cols).astype(np.float32)
    assert result.shape == (144,len(FEATURE_NAMES)) and np.isfinite(result).all()
    return result, base.astype(np.float64)


def all_features(data: Data):
    xx, bb = [], []
    for day, d in enumerate(data.dates):
        pairs = [features(data.load_kw[:day],data.pv_kw[:day],date.fromisoformat(d),a) for a in (0,1)]
        xx.append(np.concatenate([r[0] for r in pairs]))
        bb.append(np.concatenate([r[1] for r in pairs]))
    return np.stack(xx), np.stack(bb)


def forward_soc(q, actual_net_kwh, initial):
    """Load-first, interval-constant measurement feedback; no future lookahead.

    Used ONLY after today's q is fixed, to find tomorrow's observed initial SOC.
    Step 3 implements its own ledger independently.
    """
    energy = float(initial)
    for purchase, net in zip(q, actual_net_kwh):
        excess = float(purchase-net)
        if excess >= 0:
            charge = min(excess, U, max(0,(E_MAX-energy)/ETA))
            energy += ETA*charge
        else:
            discharge = min(-excess,U,max(0,(energy-E_MIN)*ETA))
            energy -= discharge/ETA
        if energy < E_MIN-1e-7 or energy > E_MAX+1e-7:
            raise AssertionError('SOC out of bounds')
    return energy


def time_label(t):
    return f'{t//6:02d}:{(t%6)*10:02d}'


