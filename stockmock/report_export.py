"""
report_export.py -- build downloadable Excel and PDF reports from a backtest
result (same shape the UI renders), so users can save/share results the way
StockMock's export works. ASCII-only.
"""
import io

import pandas as pd


def _summary_rows(res, params, name):
    m, p = res["metrics"], res["performance"]
    trades = res["trades"]
    is_opt = bool(trades) and "pnl" in trades[0]
    pf = ("%.2f" % m["pf"]) if m["pf"] != float("inf") else "inf"
    base = int(p.get("capital_base") or 0)
    rows = [("Strategy", name),
            ("From", params.get("start") or "(all data)"),
            ("To", params.get("end") or "(all data)")]
    if is_opt:
        pnls = [t["pnl"] for t in trades]
        total = sum(pnls)
        rows += [
            ("Entry / Exit", "%s - %s" % (params.get("entry_time", ""), params.get("exit_time", ""))),
            ("Lot size", params.get("lot_size", "")),
            ("Square off", params.get("square_off", "")),
            ("Margin base (Rs)", base), ("", ""),
            ("Total P&L (Rs)", int(round(total))),
            ("Total return %", p.get("total_return_pct", 0.0)),
            ("Win days %", m.get("win", 0.0)),
            ("Max drawdown %", p.get("max_drawdown_pct", 0.0)),
            ("Max drawdown (Rs)", int(p.get("max_drawdown_rs") or 0)),
            ("Profit factor", pf),
            ("Avg P&L / day (Rs)", int(round(total / len(pnls))) if pnls else 0),
            ("Best day (Rs)", int(round(max(pnls)))) if pnls else ("Best day (Rs)", 0),
            ("Worst day (Rs)", int(round(min(pnls)))) if pnls else ("Worst day (Rs)", 0),
            ("Trading days", m.get("n", 0))]
    else:                                            # equity: %-based, Rs via capital
        net = base * p.get("total_return_pct", 0.0) / 100.0
        rows += [
            ("Universe (stocks)", params.get("universe_size", "")),
            ("Capital (Rs)", base), ("", ""),
            ("Net P&L (Rs)", int(round(net))),
            ("Total return %", p.get("total_return_pct", 0.0)),
            ("CAGR %", p.get("cagr_pct", 0.0)),
            ("Win rate %", m.get("win", 0.0)),
            ("Max drawdown %", p.get("max_drawdown_pct", 0.0)),
            ("Max drawdown (Rs)", int(p.get("max_drawdown_rs") or 0)),
            ("Profit factor", pf),
            ("Trades", m.get("n", 0))]
    return rows


def _day(d):
    try:
        return pd.Timestamp(str(d)).day_name()[:3]
    except Exception:
        return ""


def _trades_df(res, name=""):
    """Per-day (or per-trade) table, StockMock-style: Date, Day, Profit, running
    Cumulative. Options add ATM/Expiry; futures don't (no strikes)."""
    trades = res["trades"]
    is_fut = "future" in (name or "").lower()
    is_opt = bool(trades) and "pnl" in trades[0]
    rows = []
    cum = 0
    if is_opt:                                           # options + futures (both P&L per day)
        for t in trades:
            pnl = int(round(t["pnl"])); cum += pnl
            row = {"Date": t["date"], "Day": _day(t["date"])}
            if not is_fut:
                row["ATM"] = t.get("atm", ""); row["Expiry"] = t.get("expiry", "")
            row["Profit (Rs)"] = pnl
            row["Cumulative (Rs)"] = cum
            row["Return %"] = t.get("ret_pct", 0.0)
            row["Outcome"] = t.get("outcome", "")
            rows.append(row)
    else:                                                # equity: per-trade
        for t in trades:
            rows.append({"Symbol": t.get("symbol", ""), "Entry date": t.get("entry_date", ""),
                         "Exit date": t.get("exit_date", ""), "Entry": t.get("entry", ""),
                         "Exit": t.get("exit", ""), "Return %": t.get("ret_pct", 0.0),
                         "Outcome": t.get("outcome", "")})
    return pd.DataFrame(rows)


def build_excel(res, params, name):
    """Return xlsx bytes: a Summary sheet + a per-day 'Result (By Date)' sheet,
    laid out like StockMock's export (headers styled, columns sized, P&L coloured)."""
    buf = io.BytesIO()
    tdf = _trades_df(res, name)
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xl:
        wb = xl.book
        hdr = wb.add_format({"bold": True, "font_color": "white", "bg_color": "#2563EB",
                             "border": 1, "align": "center"})
        pos = wb.add_format({"font_color": "#16A34A"})
        neg = wb.add_format({"font_color": "#DC2626"})

        sdf = pd.DataFrame(_summary_rows(res, params, name), columns=["Metric", "Value"])
        sdf.to_excel(xl, sheet_name="Summary", index=False)
        ws = xl.sheets["Summary"]
        ws.set_column(0, 0, 26); ws.set_column(1, 1, 22)
        for c, t in enumerate(["Metric", "Value"]):
            ws.write(0, c, t, hdr)

        tdf.to_excel(xl, sheet_name="Result (By Date)", index=False)
        ws2 = xl.sheets["Result (By Date)"]
        for c, t in enumerate(tdf.columns):
            ws2.write(0, c, t, hdr)
            ws2.set_column(c, c, 13 if t in ("Cumulative (Rs)", "Entry date", "Exit date") else 11)
        # colour the Profit column green/red
        if "Profit (Rs)" in list(tdf.columns):
            pc = list(tdf.columns).index("Profit (Rs)")
            for r in range(len(tdf)):
                v = tdf.iloc[r, pc]
                ws2.write(r + 1, pc, v, pos if v >= 0 else neg)
    return buf.getvalue()


def build_pdf(res, params, name):
    """Return a one/two-page PDF: title, summary table, per-day table."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    story = [Paragraph("Backtest Report - %s" % name, styles["Title"]), Spacer(1, 6)]

    sdata = [["Metric", "Value"]] + [[str(k), str(v)] for k, v in _summary_rows(res, params, name) if k]
    st_tbl = Table(sdata, colWidths=[70 * mm, 60 * mm])
    st_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4B3FBF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4fb")])]))
    story += [st_tbl, Spacer(1, 12), Paragraph("Per-day P&L", styles["Heading3"])]

    df = _trades_df(res, name)
    tdata = [list(df.columns)] + df.astype(str).values.tolist()
    t_tbl = Table(tdata, repeatRows=1)
    t_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4B3FBF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dddddd")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7fc")])]))
    story.append(t_tbl)
    doc.build(story)
    return buf.getvalue()
