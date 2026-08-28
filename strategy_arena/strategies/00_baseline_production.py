from strategy_arena.base import BaseStrategy  # 匯入策略基類
import pandas as pd  # 匯入 pandas

class BaselineProductionStrategy(BaseStrategy):  # 你的原始生產版對照基準 (Control Benchmark)
    def __init__(self):  # 初始化
        super().__init__(  # 呼叫父類初始化
            name="00_原始生產版基準 (Control Baseline)",  # 策略名稱
            description="4H 30MA 多空混合 + 日線 50MA 體制 + Alpha 3% 金字塔加碼 2.0x (原版)"  # 說明
        )  # 結束

    # 原始版本：完全遵從 30MA 主訊號與 Alpha 加碼，不覆寫任何過濾器
