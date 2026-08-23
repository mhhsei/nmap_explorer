"""
視障者空間導航非同步音效反饋引擎 (Audio Feedback Engine)

作用：在 Windows 終端機環境下，透過 winsound 提供非同步的音效反饋：
1. 步行踏步聲 (Footsteps)：雙音頻腳步聲（腳跟著地與腳尖離地）。
2. 撞牆碰壁音 (Collision Bump)：低頻沉重撞擊聲，提醒前方有障礙物。
3. 轉向提示音 (Turn Cue)：清脆雙音，輔助確認已轉向。
4. 抵達目的地和弦 (Arrival Chord)：大三和弦 (C5-E5-G5) 慶祝抵達。
"""
import sys
import threading

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


class SoundManager:
    """
    音效管理員 (Sound Manager)
    
    所有播放方法皆在背景 Daemon 執行緒非同步執行，絕對不阻塞主程式或 NVDA 報讀。
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def play_footsteps(self, steps: int = 2):
        """
        播放步行腳步聲
        @param steps 步數（預設 2 步，模擬左右腳前進）
        """
        if not self.enabled or not HAS_WINSOUND:
            return

        def _worker():
            try:
                for _ in range(steps):
                    winsound.Beep(240, 35)  # 腳跟著地低音
                    winsound.Beep(290, 25)  # 腳尖蹬起高音
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def play_bump_collision(self):
        """
        播放撞牆或碰壁障礙物音效
        作用：低沉重擊聲 (110Hz -> 85Hz)，直觀提醒視障者「撞到牆壁或不能走的路」。
        """
        if not self.enabled or not HAS_WINSOUND:
            return

        def _worker():
            try:
                # 沉重低頻警告音
                winsound.Beep(110, 120)
                winsound.Beep(85, 180)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def play_turn(self):
        """
        播放轉向提示音 (440Hz -> 580Hz)
        """
        if not self.enabled or not HAS_WINSOUND:
            return

        def _worker():
            try:
                winsound.Beep(440, 25)
                winsound.Beep(580, 35)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def play_arrival(self):
        """
        播放抵達目的地和弦音 (C5 -> E5 -> G5 琶音)
        """
        if not self.enabled or not HAS_WINSOUND:
            return

        def _worker():
            try:
                winsound.Beep(523, 50)  # Do (C5)
                winsound.Beep(659, 50)  # Mi (E5)
                winsound.Beep(784, 80)  # Sol (G5)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

