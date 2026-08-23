import sys
import os
from typing import Optional

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

from nmap.agent.explorer import ExplorerAgent
from nmap.agent.nlp_query import NLPQueryEngine
from nmap.accessibility.reporter import NVDAReporter


def print_nvda(text: str):
    """Print text with clean line breaks suitable for NVDA speech synthesis."""
    print(text)
    print()


def show_help():
    help_text = """
【nmap 視障者真實地圖世界探索器 - 指令說明】

一、鍵盤單鍵與方向鍵快速行走（不用按 Enter！）：
   • 【↑ 上方向鍵】或【w】：向前踏步 10 公尺 (聽腳步聲 👣)
   • 【↓ 下方向鍵】或【s】：向後退步 10 公尺
   • 【← 左方向鍵】或【a】：向左轉向 90 度 (聽轉向聲 🔄)
   • 【→ 右方向鍵】或【d】：向右轉向 90 度 (聽轉向聲 🔄)
   • 【空白鍵 Space】：重新朗讀周遭 360 度環境與店家

二、文字指令與地圖定位：
   • start <地址/座標/Google地圖連結> (例: start 淡水區北新路177號 或 start 台北車站)
   • forward [m] / f / 前進 [m]  (向前行走)
   • back [m] / b / 後退 [m]
   • left / l / 向左
   • right / r / 向右
   • turn <left/right/角度> 或 轉向 <左轉/右轉>
   • face <north/east/south/west> 或 面向 <北方/東方/南方/西方>

三、自然語言提問 (直接輸入問題即可)：
   • 附近有什麼便利商店？ / 左邊有什麼？ / 路口安全嗎？ / 這條路好走嗎？

四、系統操作：
   • status (檢視目前位置座標與方向)
   • help (顯示此說明)
   • exit / quit (結束程式)
"""
    print_nvda(help_text)


def read_user_input(prompt: str = "nmap> ") -> str:
    """
    【讀取終端機使用者輸入（支援無障礙方向鍵與單鍵即時行走）】
    
    作用：
    1. 在 Windows 終端機下使用 msvcrt 攔截實體鍵盤的「方向鍵（上/下/左/右）」與「空白鍵」。
    2. 視障者只要按一下【↑ 上鍵】就能直接向前走一步，完全不用按 Enter，操作像玩遊戲一樣直覺。
    3. 若輸入一般文字，則累積為字串並於按下 Enter 時回傳。
    """
    if not HAS_MSVCRT or not sys.stdin.isatty():
        return input(prompt).strip()

    print(prompt, end="", flush=True)
    chars = []

    while True:
        ch = msvcrt.getch()

        # 攔截方向鍵與延伸功能鍵
        if ch in (b'\x00', b'\xe0'):
            ch2 = msvcrt.getch()
            if ch2 == b'H':  # ↑ 上方向鍵：前進 1 公尺
                print("↑ [前進 1m]")
                return "forward 1"
            elif ch2 == b'P':  # ↓ 下方向鍵：後退 1 公尺
                print("↓ [後退 1m]")
                return "back 1"
            elif ch2 == b'K':  # ← 左方向鍵：左轉 90 度
                print("← [左轉 90°]")
                return "turn left"
            elif ch2 == b'M':  # → 右方向鍵：右轉 90 度
                print("→ [右轉 90°]")
                return "turn right"
            continue

        # 按下 Enter 鍵送出文字指令
        if ch in (b'\r', b'\n'):
            print()
            return "".join(chars).strip()

        # Backspace 退格鍵處理
        if ch == b'\x08':
            if chars:
                chars.pop()
                # 在終端機畫面上擦除前一個字元
                sys.stdout.write('\b \b')
                sys.stdout.flush()
            continue

        # 在緩衝區為空時按空白鍵 -> 重新查看與朗讀周遭環境
        if ch == b' ' and not chars:
            print("[查看周遭]")
            return "look"

        # Ctrl+C 或 ESC 鍵退出程式
        if ch in (b'\x03', b'\x1b'):
            print()
            return "exit"

        # 一般文字字元解碼與即時回顯
        try:
            char_str = ch.decode('utf-8', errors='ignore')
            if char_str:
                chars.append(char_str)
                sys.stdout.write(char_str)
                sys.stdout.flush()
        except Exception:
            pass


def main():
    """
    【命令列 CLI 模式主迴圈】
    作用：初始化地圖探索引擎、自然語言處理器與 NVDA 報讀器，提供終端機介面操作。
    """
    agent = ExplorerAgent()
    nlp_engine = NLPQueryEngine()
    reporter = NVDAReporter()

    print_nvda("=== nmap 視障者真實地圖世界探索系統 (NVDA 無障礙方向鍵版) ===")
    print_nvda("提示：可以使用【鍵盤方向鍵 ↑前進 ↓後退 ←左轉 →右轉】或【空白鍵】直接行走探索！")
    print_nvda("輸入 'start <地址/座標>' 定位起點，或輸入 'help' 查看說明。\n")

    # 若啟動時附帶命令列參數（例如：python cli.py "台北車站"），自動定位
    if len(sys.argv) > 1:
        initial_loc = " ".join(sys.argv[1:])
        ok, msg = agent.teleport(initial_loc)
        print_nvda(msg)
        if ok:
            print_nvda(reporter.generate_full_report(agent))


    while True:
        try:
            user_input = read_user_input("nmap> ")
        except (KeyboardInterrupt, EOFError):
            print_nvda("\n感謝使用 nmap 世界探索器，再見！")
            break

        cmd_lower = user_input.lower().strip()

        if cmd_lower in ["exit", "quit", "離開", "結束", "q"]:
            print_nvda("結束 nmap 世界探索器。")
            break

        if cmd_lower in ["help", "?", "說明", "h"]:
            show_help()
            continue

        # Pressing Space, Enter on empty line, or typing 'look' / '查看' triggers Full Report
        if not cmd_lower or cmd_lower in ["look", "ls", "查看", "環境", "space", "詳細", "k"]:
            print_nvda(reporter.generate_full_report(agent))
            continue

        # Item 3.1 Shortcut Keys: [P] Nearest POI, [R] Road & Door Numbers, [H] History
        if cmd_lower in ["p", "poi", "店家", "店家選單"]:
            pois = agent.world_model.get_nearby_pois(agent.lat, agent.lon, agent.heading_deg, radius_m=100.0)
            if pois:
                nearest = pois[0]
                print_nvda(f"【最近店家 [P]】{nearest['name']}（位於 {nearest['clock_position']} {nearest['relative_direction']} {nearest['distance_m']}m，類別: {nearest['category']}）")
            else:
                print_nvda("【最近店家 [P]】周遭 100m 內無特別設施標籤。")
            continue

        if cmd_lower in ["r", "road", "路名", "門牌"]:
            road_info = agent.world_model.get_road_info(agent.lat, agent.lon, agent.heading_deg)
            side_scan = agent.world_model.get_left_right_side_scan(agent.lat, agent.lon, agent.heading_deg, radius_m=60.0)
            door_est = agent.world_model.get_interpolated_door_numbers(agent.lat, agent.lon, agent.heading_deg)
            l_str = ", ".join(side_scan["left_side"]["house_numbers"]) or door_est["left_side_estimate"]
            r_str = ", ".join(side_scan["right_side"]["house_numbers"]) or door_est["right_side_estimate"]
            print_nvda(f"【路名與門牌 [R]】{road_info['street_name']}（{road_info['sidewalk_desc']}） | 左側: {l_str} | 右側: {r_str}")
            continue

        if cmd_lower in ["h", "history", "歷史", "紀錄"]:
            dist_km = round(agent.step_count * 1.0 / 1000.0, 3)
            print_nvda(f"【探索歷程 [H]】起點: {agent.location_label} | 總探索步數: {agent.step_count} 步 (約 {dist_km} km) | 記錄筆數: {len(agent.history)} 筆")
            continue

        if cmd_lower in ["status", "狀態"]:
            cardinal = agent.geocoder.reverse_geocode(agent.lat, agent.lon)
            lbl = cardinal["display_name"] if cardinal else agent.location_label
            print_nvda(f"目前位置: {lbl}\nGPS: ({round(agent.lat, 5)}, {round(agent.lon, 5)})\nHeading: {int(agent.heading_deg)}°\n步數: {agent.step_count}")
            continue

        # Command: start <location>
        if cmd_lower.startswith("start ") or cmd_lower.startswith("定位 "):
            loc = user_input.split(" ", 1)[1]
            print_nvda(f"正在載入地圖區域：'{loc}' ...")
            ok, msg = agent.teleport(loc)
            print_nvda(msg)
            if ok:
                print_nvda(reporter.generate_full_report(agent))
            continue

        # Single key movement shortcuts: w/a/s/d
        if cmd_lower in ["w", "up"]:
            ok, msg = agent.move("forward", 1.0)
            print_nvda(msg)
            if ok:
                print_nvda(reporter.generate_concise_report(agent))
            continue

        if cmd_lower in ["s", "down"]:
            ok, msg = agent.move("back", 1.0)
            print_nvda(msg)
            if ok:
                print_nvda(reporter.generate_concise_report(agent))
            continue

        if cmd_lower in ["a", "left_turn"]:
            ok, msg = agent.turn("left")
            print_nvda(msg)
            if ok:
                print_nvda(reporter.generate_concise_report(agent))
            continue

        if cmd_lower in ["d", "right_turn"]:
            ok, msg = agent.turn("right")
            print_nvda(msg)
            if ok:
                print_nvda(reporter.generate_concise_report(agent))
            continue

        # Command: forward / back / left / right
        parts = user_input.split()
        first_word = parts[0].lower()

        if first_word in ["forward", "f", "前進", "前"]:
            dist = float(parts[1]) if len(parts) > 1 and parts[1].replace('.', '', 1).isdigit() else None
            ok, msg = agent.move("forward", dist)
            print_nvda(msg)
            if ok:
                print_nvda(reporter.generate_concise_report(agent))
            continue

        if first_word in ["back", "backward", "b", "後退", "後"]:
            dist = float(parts[1]) if len(parts) > 1 and parts[1].replace('.', '', 1).isdigit() else None
            ok, msg = agent.move("back", dist)
            print_nvda(msg)
            if ok:
                print_nvda(reporter.generate_concise_report(agent))
            continue

        if first_word in ["left", "l", "向左"]:
            dist = float(parts[1]) if len(parts) > 1 and parts[1].replace('.', '', 1).isdigit() else None
            ok, msg = agent.move("left", dist)
            print_nvda(msg)
            if ok:
                print_nvda(reporter.generate_concise_report(agent))
            continue

        if first_word in ["right", "r", "向右"]:
            dist = float(parts[1]) if len(parts) > 1 and parts[1].replace('.', '', 1).isdigit() else None
            ok, msg = agent.move("right", dist)
            print_nvda(msg)
            if ok:
                print_nvda(reporter.generate_concise_report(agent))
            continue

        # Command: turn <val>
        if first_word in ["turn", "轉向", "旋轉"]:
            target_val = parts[1] if len(parts) > 1 else "right"
            ok, msg = agent.turn(target_val)
            print_nvda(msg)
            if ok:
                print_nvda(reporter.generate_concise_report(agent))
            continue

        # Command: face <target>
        if first_word in ["face", "面向", "朝向"]:
            target_val = parts[1] if len(parts) > 1 else "north"
            ok, msg = agent.face(target_val)
            print_nvda(msg)
            if ok:
                print_nvda(reporter.generate_concise_report(agent))
            continue

        # Command: ask <query> or natural language direct input
        query_text = user_input
        if first_word == "ask" and len(parts) > 1:
            query_text = " ".join(parts[1:])

        ans = nlp_engine.process_query(query_text, agent)
        print_nvda(ans)


if __name__ == "__main__":
    main()
