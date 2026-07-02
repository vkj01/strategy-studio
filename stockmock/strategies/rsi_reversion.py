"""
RSI Mean Reversion -- the classic contrarian oscillator strategy.

Buy when RSI drops into oversold territory (crosses below the oversold level);
exit when RSI recovers past the exit level. Wilder's RSI (matches TradingView).
"""
import numpy as np

META = {
    "key": "rsi_reversion",
    "name": "RSI Mean Reversion",
    "instrument": "equity",
    "description": ("Buy when RSI crosses below the oversold level (stock is beaten "
                    "down); sell when RSI recovers past the exit level."),
    "variables": {
        "universe_size": {"type": "int",   "label": "Number of stocks", "default": 50, "min": 5, "max": 150},
        "rsi_period":    {"type": "int",   "label": "RSI period",       "default": 14, "min": 2, "max": 50},
        "oversold":      {"type": "float", "label": "Oversold level",   "default": 30, "min": 5, "max": 45},
        "exit_level":    {"type": "float", "label": "Exit (recovery) level", "default": 55, "min": 45, "max": 90},
        "stop_loss_pct": {"type": "float", "label": "Stop-loss % (0=off)", "default": 0.0, "min": 0, "max": 50},
        "target_pct":    {"type": "float", "label": "Target % (0=off)",    "default": 0.0, "min": 0, "max": 200},
        "max_hold_days": {"type": "int",   "label": "Max hold days (0=off)", "default": 0, "min": 0, "max": 500},
        "trail_stop_pct":{"type": "float", "label": "Trailing stop % (0=off)", "default": 0.0, "min": 0, "max": 50},
        "capital":       {"type": "int",   "label": "Capital (Rs)",       "default": 1000000, "min": 10000, "max": 100000000},
        "max_positions": {"type": "int",   "label": "Max positions (0=all)", "default": 0, "min": 0, "max": 100},
        "cost_pct":      {"type": "float", "label": "Cost per side %",    "default": 0.1, "min": 0, "max": 2},
        "start":         {"type": "date",  "label": "From date", "default": None},
        "end":           {"type": "date",  "label": "To date",   "default": None},
    },
}


def _rsi(close, period):
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def signals(df, params):
    period = int(params.get("rsi_period", 14))
    oversold = float(params.get("oversold", 30))
    exit_level = float(params.get("exit_level", 55))
    rsi = _rsi(df["close"], period).to_numpy()
    prev = np.roll(rsi, 1)
    valid = ~(np.isnan(rsi) | np.isnan(prev))
    entry = valid & (rsi < oversold) & (prev >= oversold)     # crossed into oversold
    exit_ = valid & (rsi > exit_level) & (prev <= exit_level)  # recovered
    entry[0] = exit_[0] = False
    return entry, exit_
