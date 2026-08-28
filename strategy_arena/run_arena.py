import os  # 匯入作業系統模組
import sys  # 匯入系統模組
import importlib.util  # 匯入動態載入模組
import pandas as pd  # 匯入 pandas 處理表格
import matplotlib.pyplot as plt  # 匯入 matplotlib 繪製對比圖
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang TC', 'Heiti TC', 'sans-serif']  # 支援繁體中文字型
plt.rcParams['axes.unicode_minus'] = False  # 正常顯示負號
from strategy_arena.base import BaseStrategy  # 匯入策略基類
from strategy_arena.engine import load_and_prepare_data, backtest_strategy, PATH_4H_4YR, PATH_GOLD_D, PATH_DXY_D  # 匯入回測引擎

STRATEGIES_DIR = os.path.join(os.path.dirname(__file__), "strategies")  # 策略外掛資料夾路徑

def discover_strategies() -> list:  # 自動掃描 strategies/ 目錄下所有外掛檔案
    strategy_instances = []  # 儲存實例清單
    for filename in sorted(os.listdir(STRATEGIES_DIR)):  # 依檔名排序遍歷
        if filename.endswith(".py") and not filename.startswith("__"):  # 尋找非私有 Python 檔
            file_path = os.path.join(STRATEGIES_DIR, filename)  # 取得完整路徑
            module_name = filename[:-3]  # 模組名稱
            spec = importlib.util.spec_from_file_location(module_name, file_path)  # 建立模組規格
            module = importlib.util.module_from_spec(spec)  # 載入模組
            spec.loader.exec_module(module)  # 執行模組

            for attr_name in dir(module):  # 檢查模組內的所有類別
                attr = getattr(module, attr_name)  # 取得屬性
                if isinstance(attr, type) and issubclass(attr, BaseStrategy) and attr is not BaseStrategy:  # 若為繼承 BaseStrategy 之有效策略類別
                    strategy_instances.append(attr())  # 實例化策略並加入清單
    return strategy_instances  # 回傳清單

def run_arena(dataset_mode: str = "4yr"):  # 執行策略大亂鬥主程式
    print("==========================================================================================")  # 分隔線
    print(f" ⚔️ 啟動【量化策略大亂鬥競技場 (Strategy Arena)】- 數據模式: {dataset_mode.upper()}")  # 標題
    print("==========================================================================================\n")  # 分隔線

    if dataset_mode == "live":  # 2.1 年實盤模式
        csv_4h = "/Users/evan/Desktop/Github_Projects/Gold_Strategy_Watch/comex_gc1!_4h.csv"  # 實盤 4H
        csv_gd = "/Users/evan/Desktop/Github_Projects/Gold_Strategy_Watch/comex_gc1!_daily.csv"  # 實盤黃金日線
        csv_dxy = "/Users/evan/Desktop/Github_Projects/Gold_Strategy_Watch/iceus_dxy_daily.csv"  # 實盤 DXY
        raw_df = load_and_prepare_data(csv_4h, csv_gd, csv_dxy)  # 載入
        raw_df = raw_df[raw_df['timestamp'] >= '2024-07-07'].reset_index(drop=True)  # 對齊實盤期
    else:  # 預設 4 年全量模式
        raw_df = load_and_prepare_data(PATH_4H_4YR, PATH_GOLD_D, PATH_DXY_D)  # 載入 4 年數據

    print(f"📊 數據就緒: 共 {len(raw_df)} 根 4H K 線 ({raw_df['timestamp'].min()} 至 {raw_df['timestamp'].max()})\n")  # 輸出數據提示

    strategies = discover_strategies()  # 自動探索所有已註冊外掛
    print(f"🔍 成功載入 {len(strategies)} 個獨立策略插件:")  # 輸出提示
    for s in strategies:  # 列出已載入策略
        print(f"   • [{s.name}]: {s.description}")  # 印出名稱與簡介
    print("")  # 空行

    results = []  # 回測結果清單
    fig, ax = plt.subplots(figsize=(14, 8))  # 建立對比圖表

    for s in strategies:  # 逐一執行回測
        print(f"⏳ 正在撮合: {s.name} ...")  # 撮合提示
        res = backtest_strategy(s, raw_df)  # 執行精準撮合
        results.append(res)  # 收集結果

        # 繪製權益曲線
        if len(res['equity_curve']) > 0:  # 若有交易數據
            ax.plot(res['dates'], res['equity_curve'], label=f"{s.name} (+{res['total_pnl']:.1f} pts, Calmar: {res['calmar']:.2f})", linewidth=2.0)  # 繪製曲線

    # 排序結果 (依 Calmar Ratio 降冪排序)
    results = sorted(results, key=lambda x: x['calmar'], reverse=True)  # 排序

    # 整理表格
    rows = []  # 表格列清單
    for r in results:  # 遍歷結果
        rows.append({
            '排名': len(rows) + 1,  # 名次
            '策略名稱': r['name'],  # 名稱
            '總獲利 (點數)': f"{r['total_pnl']:+.2f} 點",  # 總點數
            '年化獲利': f"{r['annual_pnl']:.1f} 點/年",  # 年化獲利
            '交易筆數': f"{r['trades']} 筆",  # 筆數
            '勝率 (%)': f"{r['win_rate']:.2f}%",  # 勝率
            '盈虧比 (PF)': f"{r['pf']:.2f}",  # 盈虧比
            '最大回撤 (MDD)': f"{r['mdd']:.2f} 點",  # 最大回撤
            '夏普比率': f"{r['sharpe']:.2f}",  # 夏普
            '卡瑪比率 (Calmar)': f"{r['calmar']:.2f}"  # 卡瑪
        })  # 收集結束

    df_report = pd.DataFrame(rows)  # 轉為 DataFrame

    print("\n🏆 【策略大亂鬥競技場 (Strategy Arena) 最終排名排行榜】:")  # 標題
    print("--------------------------------------------------------------------------------------------------------------------------------")  # 分割線
    print(df_report.to_string(index=False))  # 輸出表格
    print("--------------------------------------------------------------------------------------------------------------------------------\n")  # 分割線

    # 完成並儲存權益圖
    ax.set_title(f"Strategy Arena Performance Overlay - Mode: {dataset_mode.upper()} ({raw_df['timestamp'].min().strftime('%Y-%m-%d')} ~ {raw_df['timestamp'].max().strftime('%Y-%m-%d')})", fontsize=14, fontweight='bold')  # 標題
    ax.set_ylabel("Cumulative PnL (Points)", fontsize=12)  # Y 軸
    ax.set_xlabel("Date", fontsize=12)  # X 軸
    ax.grid(True, linestyle='--', alpha=0.5)  # 網格
    ax.legend(loc='upper left', fontsize=10)  # 圖例
    fig.tight_layout()  # 自動排版
    chart_path = os.path.join(os.path.dirname(__file__), "arena_comparison_chart.png")  # 圖檔路徑
    fig.savefig(chart_path, dpi=300)  # 儲存圖片
    plt.close(fig)  # 關閉釋放
    print(f"📈 全策略累積權益曲線對比圖已儲存至: {chart_path}")  # 圖檔提示

    # 輸出 Markdown 報告
    md_path = os.path.join(os.path.dirname(__file__), "ARENA_LEADERBOARD.md")  # Markdown 路徑
    with open(md_path, "w", encoding="utf-8") as f:  # 寫入 Markdown
        f.write(f"# ⚔️ 策略大亂鬥競技場 (Strategy Arena) 排行榜\n\n")  # 大標題
        f.write(f"> 數據模式: **{dataset_mode.upper()}** (共 {len(raw_df)} 根 4H K 線，嚴格扣除點差 0.3 點與隔夜利息)\n\n")  # 說明
        f.write(df_report.to_markdown(index=False))  # 寫入表格
        f.write(f"\n\n![Arena Chart](file://{chart_path})\n")  # 圖片引用
    print(f"📄 競賽 Markdown 報告已儲存至: {md_path}\n")  # 檔案提示

if __name__ == '__main__':  # 主程式入口
    mode = "4yr" if len(sys.argv) < 2 else sys.argv[1]  # 取得命令列參數
    run_arena(dataset_mode=mode)  # 啟動競技場
