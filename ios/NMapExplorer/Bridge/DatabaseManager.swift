/**
 * iOS 原生 SQLite 資料庫與 Overture 大數據管理器 (Native Database Manager)
 * 
 * 作用：
 * 1. nmap_cache.db (讀寫快取)：以 SQLite WAL 模式儲存 Overpass API 查詢結果與地理編碼快取，加速二次查詢。
 * 2. overture_places.db (全台 193 萬筆店家資料庫)：以唯讀模式 (Read-Only) 直接在 Bundle 中掛載，
 *    搭配經緯度 B-Tree 索引 (idx_lat_lon)，查詢方圓 60 公尺內的店家僅需 1~2 毫秒，零記憶體複製消耗。
 */
import Foundation
import SQLite3

class DatabaseManager {

    static let shared = DatabaseManager()
    private var cacheDb: OpaquePointer?
    private var overtureDb: OpaquePointer?
    private let queue = DispatchQueue(label: "com.example.nmapexplorer.db", qos: .userInitiated)

    private init() {
        setupCacheDatabase()
        setupOvertureDatabase()
    }

    deinit {
        if cacheDb != nil { sqlite3_close(cacheDb) }
        if overtureDb != nil { sqlite3_close(overtureDb) }
    }

    // 初始化本機 Documents 快取資料庫 (WAL Mode)
    private func setupCacheDatabase() {
        let fileManager = FileManager.default
        guard let docDir = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first else { return }
        let targetDBPath = docDir.appendingPathComponent("nmap_cache.db")

        if !fileManager.fileExists(atPath: targetDBPath.path) {
            if let bundleDB = Bundle.main.url(forResource: "nmap_cache", withExtension: "db", subdirectory: "Resources") ??
               Bundle.main.url(forResource: "nmap_cache", withExtension: "db") {
                try? fileManager.copyItem(at: bundleDB, to: targetDBPath)
                print("[DatabaseManager] Seeded initial nmap_cache.db to Documents.")
            }
        }

        if sqlite3_open(targetDBPath.path, &cacheDb) == SQLITE_OK {
            sqlite3_exec(cacheDb, "PRAGMA journal_mode = WAL;", nil, nil, nil)
            sqlite3_exec(cacheDb, "PRAGMA synchronous = NORMAL;", nil, nil, nil)
            let createOverpass = "CREATE TABLE IF NOT EXISTS overpass_cache (query_key TEXT PRIMARY KEY, data_json TEXT NOT NULL, timestamp REAL NOT NULL);"
            let createGeocode = "CREATE TABLE IF NOT EXISTS geocode_cache (query_key TEXT PRIMARY KEY, data_json TEXT NOT NULL, timestamp REAL NOT NULL);"
            sqlite3_exec(cacheDb, createOverpass, nil, nil, nil)
            sqlite3_exec(cacheDb, createGeocode, nil, nil, nil)
        }
    }

    // 初始化全台 193 萬筆 Overture 實體店家資料庫 (Read-Only)
    private func setupOvertureDatabase() {
        let fileManager = FileManager.default
        let bundleURL = Bundle.main.url(forResource: "overture_places", withExtension: "db", subdirectory: "Resources") ??
                        Bundle.main.url(forResource: "overture_places", withExtension: "db")

        guard let overturePath = bundleURL?.path, fileManager.fileExists(atPath: overturePath) else {
            print("[DatabaseManager] overture_places.db not found in bundle.")
            return
        }

        // Open in Read-Only mode for maximum speed and zero memory duplication
        if sqlite3_open_v2(overturePath, &overtureDb, SQLITE_OPEN_READONLY | SQLITE_OPEN_FULLMUTEX, nil) == SQLITE_OK {
            print("[DatabaseManager] overture_places.db (1.93M POIs) opened successfully in Read-Only mode.")
        } else {
            print("[DatabaseManager] Failed to open overture_places.db.")
        }
    }

    /**
     * 【極速空間邊界框查詢周遭 Overture 店家】
     * 作用：利用經緯度 B-Tree 索引在 1~2 毫秒內檢索出半徑內的實體店家。
     */
    func queryNearbyOverturePlaces(lat: Double, lon: Double, radiusM: Double, completion: @escaping ([[String: Any]]) -> Void) {

        queue.async {
            guard let db = self.overtureDb else {
                completion([])
                return
            }

            let latDelta = radiusM / 111139.0
            let lonDelta = radiusM / (111139.0 * cos(lat * .pi / 180.0))
            let minLat = lat - latDelta
            let maxLat = lat + latDelta
            let minLon = lon - lonDelta
            let maxLon = lon + lonDelta

            let query = "SELECT name, category, lat, lon FROM overture_places WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? LIMIT 80;"
            var statement: OpaquePointer?
            var results: [[String: Any]] = []

            if sqlite3_prepare_v2(db, query, -1, &statement, nil) == SQLITE_OK {
                sqlite3_bind_double(statement, 1, minLat)
                sqlite3_bind_double(statement, 2, maxLat)
                sqlite3_bind_double(statement, 3, minLon)
                sqlite3_bind_double(statement, 4, maxLon)

                while sqlite3_step(statement) == SQLITE_ROW {
                    let nameC = sqlite3_column_text(statement, 0)
                    let catC = sqlite3_column_text(statement, 1)
                    let pLat = sqlite3_column_double(statement, 2)
                    let pLon = sqlite3_column_double(statement, 3)

                    let rawName = nameC != nil ? String(cString: nameC!) : "未知名稱"
                    let cleanName = rawName.trimmingCharacters(in: CharacterSet.controlCharacters)
                    let category = catC != nil ? String(cString: catC!) : "poi"

                    results.append([
                        "name": cleanName,
                        "category": category,
                        "lat": pLat,
                        "lon": pLon
                    ])
                }
            }
            sqlite3_finalize(statement)
            completion(results)
        }
    }

    func getOverpass(queryKey: String, completion: @escaping (String?) -> Void) {
        queue.async {
            guard let db = self.cacheDb else { completion(nil); return }
            var statement: OpaquePointer?
            let query = "SELECT data_json FROM overpass_cache WHERE query_key = ? LIMIT 1;"
            var result: String? = nil

            if sqlite3_prepare_v2(db, query, -1, &statement, nil) == SQLITE_OK {
                sqlite3_bind_text(statement, 1, (queryKey as NSString).utf8String, -1, nil)
                if sqlite3_step(statement) == SQLITE_ROW {
                    if let cString = sqlite3_column_text(statement, 0) {
                        result = String(cString: cString)
                    }
                }
            }
            sqlite3_finalize(statement)
            completion(result)
        }
    }

    func setOverpass(queryKey: String, dataJson: String) {
        queue.async {
            guard let db = self.cacheDb else { return }
            var statement: OpaquePointer?
            let query = "INSERT OR REPLACE INTO overpass_cache (query_key, data_json, timestamp) VALUES (?, ?, ?);"
            let now = Date().timeIntervalSince1970

            if sqlite3_prepare_v2(db, query, -1, &statement, nil) == SQLITE_OK {
                sqlite3_bind_text(statement, 1, (queryKey as NSString).utf8String, -1, nil)
                sqlite3_bind_text(statement, 2, (dataJson as NSString).utf8String, -1, nil)
                sqlite3_bind_double(statement, 3, now)
                sqlite3_step(statement)
            }
            sqlite3_finalize(statement)
        }
    }
}
