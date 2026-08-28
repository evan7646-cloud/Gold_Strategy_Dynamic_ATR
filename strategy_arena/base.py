import pandas as pd  # 匯入 pandas 處理表格數據
from abc import ABC, abstractmethod  # 匯入抽象類別庫以規範策略介面

class BaseStrategy(ABC):  # 所有策略外掛必須繼承的統一抽象基類
    def __init__(self, name: str, description: str):  # 策略初始化建構函數
        self.name = name  # 策略顯示名稱 (例如: '01_RSI頂部鈍化過濾')
        self.description = description  # 策略邏輯一句話簡介

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:  # 特徵與指標計算掛鉤函數 (子類可覆寫以新增自定義指標如 MACD/RSI/SuperTrend)
        return df  # 預設直接回傳原始資料表

    def filter_entry(self, row: pd.Series, is_long: bool, default_signal: bool) -> bool:  # 進場過濾鉤子：決定是否允許開倉 (可用於 VETO 假突破或頂部誘多)
        return default_signal  # 預設遵從 30MA 主訊號

    def calculate_pyramid_size(self, row: pd.Series, is_long: bool, base_units: float) -> float:  # 加碼手數調制鉤子：決定加碼倉手數 (可用於 ATR 波動度調制或硬上限)
        return base_units  # 預設遵從 Alpha 原始手數 (例如 2.0x 或 1.0x)

    def filter_exit(self, row: pd.Series, pos_dict: dict, current_stop: float) -> float:  # 出場與停損調整鉤子：可自定義動態跟蹤停損演算法
        return current_stop  # 預設遵從 1.0 * ATR 跟蹤停損價位
