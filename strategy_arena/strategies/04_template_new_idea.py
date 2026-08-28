from strategy_arena.base import BaseStrategy  # 匯入策略基類
import pandas as pd  # 匯入 pandas 模組

class MyNewStrategyIdea(BaseStrategy):  # 使用者專屬新策略測試模板 (只需修改此處即可)
    def __init__(self):  # 初始化
        super().__init__(  # 呼叫基類初始化
            name="04_我的自定義新策略測試",  # ✏️ 請自訂你的策略名稱
            description="測試新的濾網或加碼邏輯 (複製此檔並修改即可自動參與全策略大亂鬥)"  # ✏️ 填寫策略簡介
        )

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:  # 步驟 1: 在此計算你需要的新指標 (例如 MACD, KD, 布林通道)
        # 範例: 計算 20 週期布林通道
        df['bb_mid'] = df['close'].rolling(20).mean()  # 布林中軌
        df['bb_std'] = df['close'].rolling(20).std()  # 標準差
        df['bb_upper'] = df['bb_mid'] + (2.0 * df['bb_std'])  # 上軌
        df['bb_lower'] = df['bb_mid'] - (2.0 * df['bb_std'])  # 下軌
        return df  # 回傳處理後的資料表

    def filter_entry(self, row: pd.Series, is_long: bool, default_signal: bool) -> bool:  # 步驟 2: 自定義進場濾網
        if not default_signal:  # 若原本 30MA 就沒有觸發
            return False  # 不進場
        # 範例: 只有在收盤價未突破布林上軌時才買進 (避免極端超買追高)
        if is_long and row['close'] > row['bb_upper']:  # 碰觸布林上軌
            return False  # 拒絕進場
        return True  # 允許進場

    def calculate_pyramid_size(self, row: pd.Series, is_long: bool, base_units: float) -> float:  # 步驟 3: 自定義加碼手數
        return base_units  # 預設維持 Alpha 基準手數 (例如 2.0x)
