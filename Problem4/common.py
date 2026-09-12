"""Shared paths, variable-price data and physical constants for Problem 4."""
from pathlib import Path
import importlib.util
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("problem2_common",ROOT/"Problem2"/"common.py")
problem2_common=importlib.util.module_from_spec(spec);sys_modules=__import__("sys").modules
sys_modules[spec.name]=problem2_common;spec.loader.exec_module(problem2_common)
load_data,read_xlsx,sha256=problem2_common.load_data,problem2_common.read_xlsx,problem2_common.sha256

DT = 1 / 6
ETA = 0.9
EMIN, EMAX, E0, U = 1200.0, 10800.0, 6000.0, 5000 / 6


def load_all():
    data = load_data()
    rows = read_xlsx(ROOT / "C题" / "附件" / "附件4.xlsx")["Sheet1"]
    if len(rows) != 366 or any(len(row) != 145 for row in rows):
        raise ValueError("附件4应包含表头和365天、每天144个电价")
    price = np.asarray([row[1:] for row in rows[1:]], dtype=float)
    if not np.isfinite(price).all() or (price <= 0).any():
        raise ValueError("附件4电价必须为有限正数")
    return data, price


def label(t):
    return f"{t // 6}:{10 * (t % 6):02d}"
