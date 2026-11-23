"""Vibe-Trading SignalEngine template: 50/200 SMA trend filter with RSI pullback entries.
The engine fills signal[t] at the t+1 open. Do NOT shift signals yourself.
Declare warmup_bars >= 200 in config.json."""
from typing import Dict
import pandas as pd


class SignalEngine:
    def __init__(self, fast: int = 50, slow: int = 200, rsi_len: int = 14, rsi_entry: float = 35.0, rsi_exit: float = 70.0):
        self.fast, self.slow, self.rsi_len = fast, slow, rsi_len
        self.rsi_entry, self.rsi_exit = rsi_entry, rsi_exit

    @staticmethod
    def _rsi(close: pd.Series, n: int) -> pd.Series:
        d = close.diff()
        up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
        dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
        return 100 - 100 / (1 + up / dn.replace(0, 1e-12))

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        out = {}
        for code, df in data_map.items():
            c = df["close"]
            trend = c.rolling(self.fast).mean() > c.rolling(self.slow).mean()
            rsi = self._rsi(c, self.rsi_len)
            sig = pd.Series(float("nan"), index=df.index)
            sig[trend & (rsi < self.rsi_entry)] = 1.0
            sig[(~trend) | (rsi > self.rsi_exit)] = 0.0
            out[code] = sig.ffill().fillna(0.0).clip(-1, 1)
        return out
