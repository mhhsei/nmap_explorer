"""
純 Python 2D 空間網格索引 (Pure Python Grid Spatial Index)

作用：
1. 替代依賴 C++ 函式庫的 libspatialindex / rtree，確保在 Android (Chaquopy) 和 iOS 環境下 100% 免編譯原生執行。
2. 將地理空間劃分為 500m x 500m 的網格方塊 (Grid Cells)。
3. 當查詢「附近 100 公尺有什麼店家或道路」時，只需篩選相鄰的 4~9 個網格，查詢速度從 O(N) 降低至 O(1)。
"""
from typing import Any, List, Tuple, Generator, Dict


class GridSpatialIndex:
    """
    純 Python 網格空間索引管理器
    """
    def __init__(self, cell_size_deg: float = 0.005): # 約 500m x 500m
        self.cell_size = cell_size_deg
        self.grid: Dict[Tuple[int, int], List[Tuple[int, Tuple[float, float, float, float], Any]]] = {}

    def _get_cell(self, lon: float, lat: float) -> Tuple[int, int]:
        """計算經緯度座標所屬的網格編號 (cell_x, cell_y)"""
        return (int(lon / self.cell_size), int(lat / self.cell_size))

    def insert(self, id: int, bounds: Tuple[float, float, float, float], obj: Any):
        """
        【插入空間物件到對應網格】
        @param id 物件唯一識別碼
        @param bounds 邊界框 (min_lon, min_lat, max_lon, max_lat)
        @param obj 空間物件本身（如道路、店家、建築物）
        """
        min_lon, min_lat, max_lon, max_lat = bounds
        min_cell = self._get_cell(min_lon, min_lat)
        max_cell = self._get_cell(max_lon, max_lat)

        for x in range(min_cell[0], max_cell[0] + 1):
            for y in range(min_cell[1], max_cell[1] + 1):
                cell = (x, y)
                if cell not in self.grid:
                    self.grid[cell] = []
                self.grid[cell].append((id, bounds, obj))

    def intersection(self, bounds: Tuple[float, float, float, float], objects: bool = True) -> Generator[Any, None, None]:
        """
        【查詢與指定邊界框重疊的所有空間物件】
        作用：只掃描涵蓋網格內的項目，並透過 Bounding Box 重疊檢查過濾，防止全表暴力掃描。
        """
        min_lon, min_lat, max_lon, max_lat = bounds
        min_cell = self._get_cell(min_lon, min_lat)
        max_cell = self._get_cell(max_lon, max_lat)

        seen_ids = set()
        
        class MockItem:
            def __init__(self, obj):
                self.object = obj

        for x in range(min_cell[0], max_cell[0] + 1):
            for y in range(min_cell[1], max_cell[1] + 1):
                cell = (x, y)
                if cell in self.grid:
                    for item_id, item_bounds, obj in self.grid[cell]:
                        if item_id not in seen_ids:
                            # 檢查邊界是否真的重疊
                            ib_min_lon, ib_min_lat, ib_max_lon, ib_max_lat = item_bounds
                            if not (ib_max_lon < min_lon or ib_min_lon > max_lon or ib_max_lat < min_lat or ib_min_lat > max_lat):
                                seen_ids.add(item_id)
                                if objects:
                                    yield MockItem(obj)
                                else:
                                    yield item_id

