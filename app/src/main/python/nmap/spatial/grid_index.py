from typing import Any, List, Tuple, Generator, Dict

class GridSpatialIndex:
    """
    純 Python 網格空間索引，替代 C 擴展的 rtree。
    對於 POI 數量在數萬以內的場景（例如半徑 5 公里內的 POI），效率足夠快。
    """
    def __init__(self, cell_size_deg: float = 0.005): # 約 500m x 500m
        self.cell_size = cell_size_deg
        self.grid: Dict[Tuple[int, int], List[Tuple[int, Tuple[float, float, float, float], Any]]] = {}

    def _get_cell(self, lon: float, lat: float) -> Tuple[int, int]:
        return (int(lon / self.cell_size), int(lat / self.cell_size))

    def insert(self, id: int, bounds: Tuple[float, float, float, float], obj: Any):
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
