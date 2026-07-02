"""
extract_options.py -- one-time: pull the daily NIFTY OPT + IDX zips out of the
nested weekly archives into a single flat local folder (outside OneDrive).

Keeps only NSE_OPT_TICK / NSE_IDX_TICK (skips FUT + OPT_CONTINUOUS to save space).
The options engine reads NIFTY contracts on demand from these daily zips.
"""
import os
import shutil
import tempfile
import zipfile

DEST = r"C:\quant_data\options_raw"
OUTERS = [r"C:\Users\vises\Downloads\Last_3Month.zip",
          r"C:\Users\vises\Downloads\data.zip"]
KEEP = ("NSE_OPT_TICK_", "NSE_IDX_TICK_")

os.makedirs(DEST, exist_ok=True)
tmp = tempfile.mkdtemp(prefix="opt_extract_")
count = 0
try:
    for outer in OUTERS:
        with zipfile.ZipFile(outer) as oz:
            weeks = [n for n in oz.namelist() if n.lower().endswith(".zip")]
            for w in weeks:
                wk = oz.extract(w, tmp)
                with zipfile.ZipFile(wk) as wz:
                    for dn in wz.namelist():
                        base = os.path.basename(dn)
                        if base.startswith(KEEP) and base.endswith(".zip"):
                            out = os.path.join(DEST, base)
                            if not os.path.exists(out):
                                with wz.open(dn) as src, open(out, "wb") as dst:
                                    shutil.copyfileobj(src, dst)
                                count += 1
                os.remove(wk)
                print("extracted week:", os.path.basename(w), "| daily zips so far:", count, flush=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("DONE. daily zips in %s: %d" % (DEST, count))
