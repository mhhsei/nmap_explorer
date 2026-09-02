import os
import zipfile
import struct
import math

class SrtmReader:
    def __init__(self, zip_path="data/taiwan_srtm3.zip"):
        self.zip_path = os.path.join(os.path.dirname(__file__), '..', '..', zip_path)
        if not os.path.exists(self.zip_path):
            self.zf = None
        else:
            self.zf = zipfile.ZipFile(self.zip_path, 'r')
            self.namelist = set(self.zf.namelist())
    
    def get_elevation(self, lat, lon):
        if not self.zf:
            return None
            
        lat_int = math.floor(lat)
        lon_int = math.floor(lon)
        
        lat_str = f"N{lat_int:02d}" if lat_int >= 0 else f"S{-lat_int:02d}"
        lon_str = f"E{lon_int:03d}" if lon_int >= 0 else f"W{-lon_int:03d}"
        
        filename = f"{lat_str}{lon_str}.hgt"
        
        if filename not in self.namelist:
            return None
            
        # Get relative position in the tile
        # SRTM grid: upper left is (lat_int + 1, lon_int)
        # However, our filename is the bottom left corner (lat_int, lon_int)
        # The data starts from upper-left, row by row.
        # So row 0 is lat_int + 1, row 1200 is lat_int.
        row_float = 1.0 - (lat - lat_int) 
        col_float = (lon - lon_int)
        
        resolution = 1201
            
        row = int(row_float * (resolution - 1))
        col = int(col_float * (resolution - 1))
        
        if row < 0 or row >= resolution or col < 0 or col >= resolution:
            return None
        
        # position in file
        pos = (row * resolution + col) * 2
        
        try:
            with self.zf.open(filename, 'r') as f:
                # In Python zipfile, seek() on compressed files might read everything up to 'pos'.
                # Since the files are DEFLATED, this might be slightly slow but for 2.8MB it's millisecond-level.
                # A better approach would be to cache the decompressed tile in memory, 
                # but to save memory we just read it. 2.8MB decompression is very fast in Python.
                f.seek(pos)
                data = f.read(2)
                if len(data) == 2:
                    elev = struct.unpack('>h', data)[0]
                    if elev == -32768:
                        return None
                    return float(elev)
        except Exception as e:
            return None
            
        return None

# Singleton instance
_srtm_reader = None

def get_elevation(lat, lon):
    global _srtm_reader
    if _srtm_reader is None:
        _srtm_reader = SrtmReader()
    return _srtm_reader.get_elevation(lat, lon)

if __name__ == "__main__":
    # Test
    # Tamsui is roughly 25.17, 121.44
    elev = get_elevation(25.17, 121.44)
    print(f"Elevation at Tamsui (25.17, 121.44): {elev}")
