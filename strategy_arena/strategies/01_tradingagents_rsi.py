from strategy_arena.base import BaseStrategy  # 匯入策略基類
import pandas as pd  # 匯入 pandas

class TradingAgentsRsiGuardStrategy(BaseStrategy):  # 開源 TradingAgents 多 Agent 頂部鈍化過濾策略
    def __init__(self, rsi_overbought: float = 78.0, rsi_oversold: float = 22.0):  # 初始化
        super().__init__(  # 呼叫父類
            name="01_TradingAgents_RSI鈍化防誘多",  # 策略名稱
            description=f"在 4H RSI > {rsi_overbought} 超買鈍化時一票否決做多，RSI < {rsi_oversold} 否決做空"  # 說明
        )
        self.rsi_ob = rsi_overbought  # 超買閾值
        self.rsi_os = rsi_oversold  # 超賣閾值

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:  # 計算 14 週期 RSI
        delta = df['close'].diff()  # 價格差
        gain = delta.where(delta > 0, 0).rolling(14).mean()  # 上漲均值
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()  # 下跌均值
        rs = gain / loss  # 相對強弱比
        df['rsi14'] = 100 - (100 / (1 + rs))  # RSI
        return df  # 回傳資料表

    def filter_entry(self, row: pd.Series, is_long: bool, default_signal: bool) -> bool:  # 進場過濾
        if not default_signal:  # 原始若無訊號則直接放棄
            return False  # 放棄
        rsi = row.get('rsi14', 50.0)  # 取得當前 RSI
        if is_long and rsi > self.rsi_ob:  # 多頭過熱不追高
            return False  # 否決進場
        if not is_long and rsi < self.rsi_os:  # 空頭過度超賣不殺低
            return False  # 否決進場
        return True  # 通過
