from strategy_arena.base import BaseStrategy  # 匯入策略基類
import pandas as pd  # 匯入 pandas
import numpy as np  # 匯入 numpy

class SuperTrendFilterStrategy(BaseStrategy):  # 新策略示例：SuperTrend 雙重趨勢濾網
    def __init__(self, atr_multiplier: float = 3.0, atr_period: int = 10):  # 初始化
        super().__init__(  # 呼叫父類
            name="03_SuperTrend_雙重趨勢濾網",  # 策略名稱
            description=f"在 4H 30MA 突破之餘，強制要求價格處於 SuperTrend({atr_period}, {atr_multiplier}) 綠色多頭軌道上才准進場"  # 說明
        )
        self.mult = atr_multiplier  # ATR 乘數
        self.period = atr_period  # ATR 週期

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:  # 計算 SuperTrend 指標
        high, low, close = df['high'], df['low'], df['close']  # 取價格
        hl2 = (high + low) / 2.0  # 中間價
        tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)  # TR
        atr = tr.rolling(self.period).mean()  # ATR

        upperband = hl2 + (self.mult * atr)  # 上軌
        lowerband = hl2 - (self.mult * atr)  # 下軌
        in_uptrend = pd.Series(True, index=df.index)  # 趨勢方向序列

        for i in range(1, len(df)):  # 計算軌道黏著
            if close.iloc[i] > upperband.iloc[i-1]:
                in_uptrend.iloc[i] = True
            elif close.iloc[i] < lowerband.iloc[i-1]:
                in_uptrend.iloc[i] = False
            else:
                in_uptrend.iloc[i] = in_uptrend.iloc[i-1]
                if in_uptrend.iloc[i] and lowerband.iloc[i] < lowerband.iloc[i-1]:
                    lowerband.iloc[i] = lowerband.iloc[i-1]
                if not in_uptrend.iloc[i] and upperband.iloc[i] > upperband.iloc[i-1]:
                    upperband.iloc[i] = upperband.iloc[i-1]

        df['supertrend_uptrend'] = in_uptrend  # 寫入趨勢標記
        return df  # 回傳資料表

    def filter_entry(self, row: pd.Series, is_long: bool, default_signal: bool) -> bool:  # 進場過濾
        if not default_signal:  # 若無 30MA 訊號
            return False  # 放棄
        is_st_up = row.get('supertrend_uptrend', True)  # 取得 SuperTrend 狀態
        if is_long and not is_st_up:  # 若做多但 SuperTrend 處於空頭通道
            return False  # 否決進場
        if not is_long and is_st_up:  # 若做空但 SuperTrend 處於多頭通道
            return False  # 否決進場
        return True  # 允許進場
