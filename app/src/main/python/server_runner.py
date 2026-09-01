"""
後端伺服器背景執行緒啟動器 (Server Runner)

作用：讓 Android 的 Kotlin 原生程式能透過 Chaquopy 在背景執行緒啟動 Python Bottle 伺服器。
好比在手機背景悄悄架設一個微型網站，專門提供前端網頁各種地圖計算與語音資訊。
"""
import os
import threading
import socket
from bottle import run

def is_server_alive(host="127.0.0.1", port=8000):
    """
    確認 Bottle HTTP 伺服器是否真正處於存活且能回應請求之狀態
    
    作用：避免單純 socket connect 抓到處於 TIME_WAIT 或殭屍狀態之通訊埠而誤判跳過啟動。
    """
    import urllib.request
    try:
        url = f"http://{host}:{port}/api/status"
        req = urllib.request.Request(url, headers={'User-Agent': 'NMapWarmup/1.0'})
        with urllib.request.urlopen(req, timeout=0.35) as response:
            return response.status in (200, 404)
    except Exception:
        return False

def start_server_in_background(host="127.0.0.1", port=8000, data_dir=None):
    """
    在背景守護執行緒 (Daemon Thread) 啟動 Bottle HTTP 伺服器
    
    @param host 監聽的主機位址（預設 127.0.0.1 本機）
    @param port 監聽的通訊埠（預設 8000）
    @param data_dir 自訂資料庫儲存目錄（Android 內部/外部儲存空間路徑）
    """
    if data_dir:
        os.environ["NMAP_DATA_DIR"] = str(data_dir)
        try:
            os.makedirs(data_dir, exist_ok=True)
        except Exception:
            pass

    # 若該 Port 已經有正常服務回應 HTTP，直接返回既有服務
    if is_server_alive(host, port):
        import logging
        logging.info(f"Bottle HTTP server is already responding on port {port}, reusing existing instance.")
        return None
        
    def _run():
        try:
            from server import app
            # 靜默啟動 Bottle 伺服器
            run(app, host=host, port=port, quiet=True)
        except OSError as e:
            # 若發生通訊埠佔用衝突且服務已活則忽略，其餘錯誤照常記錄
            if "Address already in use" in str(e) or "10048" in str(e) or "98" in str(e):
                import logging
                logging.warning(f"Port {port} address already in use: {e}")
            else:
                import logging
                logging.error(f"Bottle server startup error: {e}")
        except Exception as e:
            import logging
            logging.error(f"Unexpected server startup exception: {e}")
    
    # 建立背景守護執行緒，當主 App 關閉時此執行緒會自動退出
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


