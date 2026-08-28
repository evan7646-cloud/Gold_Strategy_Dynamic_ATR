from strategy_arena.base import BaseStrategy  # 匯入策略基類
import pandas as pd  # 匯入 pandas

class FiftyOneBitquantAtrStrategy(BaseStrategy):  # 開源 51Bitquant 波動度自適應調倉策略
    def __init__(self, baseline_atr: float = 16.0, max_mult: float = 2.5, min_mult: float = 0.5):  # 初始化
        super().__init__(  # 呼叫父類
            name="02_51Bitquant_波動度自適應調倉",  # 策略名稱
            description=f"手數依據 Baseline ATR ({baseline_atr}) / 當前 ATR 動態縮放 ({min_mult}x ~ {max_mult}x)"  # 說明
        )
        self.baseline_atr = baseline_atr  # 基準 ATR
        self.max_mult = max_mult  # 最大乘數
        self.min_mult = min_mult  # 最小乘數

    def calculate_pyramid_size(self, row: pd.Series, is_long: bool, base_units: float) -> float:  # 調制手數
        tatr = row.get('atr14_4h', 14.0)  # 取得當前 ATR
        atr_scale = self.baseline_atr / max(tatr, 4.0)  # 計算波動度倒數係數
        dynamic_u = round(min(self.max_mult, max(self.min_mult, base_units * atr_scale)), 2)  # 調制手數
        return dynamic_u  # 回傳調制後加碼手數
