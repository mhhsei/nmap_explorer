import sys
import threading

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


class SoundManager:
    """
    Non-blocking Audio Feedback Engine for Visually Impaired Spatial Navigation.
    Provides sound effects for:
    1. Footsteps when walking
    2. Obstacle / Wall collision bump sounds
    3. Turning / Orientation rotation audio cues
    4. Arriving / Teleporting sound
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def play_footsteps(self, steps: int = 2):
        """Play footstep sound effect asynchronously."""
        if not self.enabled or not HAS_WINSOUND:
            return

        def _worker():
            try:
                for _ in range(steps):
                    winsound.Beep(240, 35)  # Heel strike
                    winsound.Beep(290, 25)  # Toe push-off
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def play_bump_collision(self):
        """Play obstacle/wall collision bump sound effect asynchronously."""
        if not self.enabled or not HAS_WINSOUND:
            return

        def _worker():
            try:
                # Heavy thud / warning bump frequency
                winsound.Beep(110, 120)
                winsound.Beep(85, 180)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def play_turn(self):
        """Play orientation rotation audio cue asynchronously."""
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
        """Play location arrival sound effect asynchronously."""
        if not self.enabled or not HAS_WINSOUND:
            return

        def _worker():
            try:
                winsound.Beep(523, 50)  # C5
                winsound.Beep(659, 50)  # E5
                winsound.Beep(784, 80)  # G5
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()
