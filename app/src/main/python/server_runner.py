"""
後端伺服器背景執行緒啟動器 (Server Runner)

作用：讓 Android 的 Kotlin 原生程式能透過 Chaquopy 在背景執行緒啟動 Python Bottle 伺服器。
好比在手機背景悄悄架設一個微型網站，專門提供前端網頁各種地圖計算與語音資訊。
"""
import os
import threading
import socket
from bottle import run

def is_port_in_use(port):
    """
    檢查指定的通訊埠 (Port) 是否已經被佔用
    
    作用：嘗試與本機通訊埠建立連線，若連線成功表示伺服器已經在跑，避免重複啟動報錯。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

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

    # 若該 Port 已經有服務在運作，直接跳過啟動
    if is_port_in_use(port):
        import logging
        logging.warning(f"Port {port} is already in use, skipping server start.")
        return None
        
    from server import app
    def _run():
        try:
            # 靜默啟動 Bottle 伺服器
            run(app, host=host, port=port, quiet=True)
        except OSError as e:
            # 若發生通訊埠佔用衝突則忽略，其餘錯誤照常拋出
            if "Address already in use" in str(e):
                pass
            else:
                raise e
    
    # 建立背景守護執行緒，當主 App 關閉時此執行緒會自動退出
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


