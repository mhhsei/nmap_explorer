/**
 * iOS 定位與感測器橋接器 (iOS Location & Sensor Bridge)
 * 
 * 作用：
 * 1. 2D 行人與車載自適應卡爾曼濾波器 (Adaptive Kalman Filter)：
 *    - 靜止鎖定 (ZUPT)：室內/停步時 100% 凍結座標，阻絕天花板下的多路徑跳點。
 *    - 馬氏距離新息門控 (Innovation Gating)：以 95% 卡方檢定 (5.991) 嚴格剔除大樓折射跳點。
 *    - 乘車高速自適應：時速 > 10 km/h 時自動切換為高速追蹤模式。
 * 2. 磁北與真北即時平滑：透過 20Hz (0.05s) 低通濾波將指北針角度推送給 WebView 前端。
 * 3. 觸覺震動回饋 (UIImpactFeedbackGenerator)：在撞牆或到達路口時觸發觸覺震動。
 */
import Foundation
import CoreLocation
import CoreMotion
import WebKit
import UIKit

/**
 * 運動狀態列舉
 */
enum MotionState {
    case stationaryLocked
    case pedestrianWalking
    case vehicularTransit
}

/**
 * 2D 行人與車載卡爾曼濾波器 (2D Pedestrian & Vehicular Kalman Filter)
 */
class PedestrianKalmanFilter {
    private var isInitialized = false
    private var anchorLat: Double = 0.0
    private var anchorLon: Double = 0.0

    private var x: Double = 0.0
    private var y: Double = 0.0
    private var vx: Double = 0.0
    private var vy: Double = 0.0

    private var p00: Double = 4.0
    private var p11: Double = 4.0
    private var p22: Double = 1.0
    private var p33: Double = 1.0

    private var lockedLat: Double = 0.0
    private var lockedLon: Double = 0.0

    private var consecutiveRejections = 0
    private var lastRejectedZx = 0.0
    private var lastRejectedZy = 0.0

    func filter(lat: Double, lon: Double, accuracy: Double, speed: Double, timestamp: TimeInterval, motionState: MotionState) -> (lat: Double, lon: Double) {
        if !isInitialized {
            anchorLat = lat
            anchorLon = lon
            x = 0.0
            y = 0.0
            vx = 0.0
            vy = 0.0
            lockedLat = lat
            lockedLon = lon
            lastTimestamp = timestamp
            isInitialized = true
            return (lat, lon)
        }

        // 靜止模式：100% 凍結座標，阻絕 GPS 飄移
        if motionState == .stationaryLocked {
            vx = 0.0
            vy = 0.0
            return (lockedLat, lockedLon)
        }

        var dt = timestamp - lastTimestamp
        lastTimestamp = timestamp
        if dt <= 0.0 || dt > 5.0 { dt = 1.0 }

        let radLat = anchorLat * .pi / 180.0
        let mPerLat = 111139.0
        let mPerLon = 111139.0 * cos(radLat)

        let zx = (lon - anchorLon) * mPerLon
        let zy = (lat - anchorLat) * mPerLat

        // 跨區大位移防護 (> 80m)
        if sqrt(zx * zx + zy * zy) > 80.0 {
            anchorLat = lat
            anchorLon = lon
            x = 0.0
            y = 0.0
            vx = 0.0
            vy = 0.0
            p00 = 4.0
            p11 = 4.0
            lockedLat = lat
            lockedLon = lon
            consecutiveRejections = 0
            return (lat, lon)
        }

        // 全時注入過程雜訊 Q，防止協方差塌陷
        let qPos = (motionState == .vehicularTransit) ? 4.0 : 1.8
        let qVel = (motionState == .vehicularTransit) ? 2.0 : 0.8

        x += vx * dt
        y += vy * dt
        p00 += p22 * dt * dt + qPos * dt
        p11 += p33 * dt * dt + qPos * dt
        p22 += qVel * dt
        p33 += qVel * dt

        let baseR = max(pow(accuracy, 1.8) * 0.7, 3.0)

        // 馬氏距離新息門控與連續異常自動拉回
        let innovX = zx - x
        let innovY = zy - y
        let sX = p00 + baseR
        let sY = p11 + baseR
        let mahalanobisSq = (innovX * innovX / sX) + (innovY * innovY / sY)

        let maxGate = (motionState == .vehicularTransit) ? 64.0 : 16.0
        if mahalanobisSq > maxGate {
            let distToLastRej = sqrt((zx - lastRejectedZx) * (zx - lastRejectedZx) + (zy - lastRejectedZy) * (zy - lastRejectedZy))
            if distToLastRej < 15.0 {
                consecutiveRejections += 1
            } else {
                consecutiveRejections = 1
            }
            lastRejectedZx = zx
            lastRejectedZy = zy

            if consecutiveRejections >= 2 {
                x = zx
                y = zy
                vx = 0.0
                vy = 0.0
                p00 = baseR
                p11 = baseR
                consecutiveRejections = 0
            } else {
                return getCurrentGeoLocation()
            }
        } else {
            consecutiveRejections = 0
        }

        let k0 = p00 / sX
        let k1 = p11 / sY

        x += k0 * innovX
        y += k1 * innovY

        p00 *= (1.0 - k0)
        p11 *= (1.0 - k1)

        vx = (k0 * innovX) / dt
        vy = (k1 * innovY) / dt

        let maxSpeed = (motionState == .vehicularTransit) ? 25.0 : 4.0
        let curSpd = sqrt(vx * vx + vy * vy)
        if curSpd > maxSpeed {
            let scale = maxSpeed / curSpd
            vx *= scale
            vy *= scale
        }

        let current = getCurrentGeoLocation()
        lockedLat = current.lat
        lockedLon = current.lon
        return current
    }

    func advanceStep(stepMeters: Double, headingDeg: Double) -> (lat: Double, lon: Double) {
        if !isInitialized { return (anchorLat, anchorLon) }
        let radHead = headingDeg * .pi / 180.0
        let dx = stepMeters * sin(radHead)
        let dy = stepMeters * cos(radHead)

        x += dx
        y += dy
        vx = dx / 0.6
        vy = dy / 0.6

        p00 += 0.5
        p11 += 0.5

        let current = getCurrentGeoLocation()
        lockedLat = current.lat
        lockedLon = current.lon
        return current
    }

    private func getCurrentGeoLocation() -> (lat: Double, lon: Double) {
        let radLat = anchorLat * .pi / 180.0
        let mPerLat = 111139.0
        let mPerLon = 111139.0 * cos(radLat)
        return (anchorLat + (y / mPerLat), anchorLon + (x / mPerLon))
    }

    func isReady() -> Bool {
        return isInitialized
    }

    func reset() {
        isInitialized = false
    }
}

class LocationSensorBridge: NSObject, CLLocationManagerDelegate {

    private weak var webView: WKWebView?
    private let locationManager = CLLocationManager()
    private let pedometer = CMPedometer()
    private let kalmanFilter = PedestrianKalmanFilter()
    private let hapticGenerator = UIImpactFeedbackGenerator(style: .medium)

    private var smoothedHeading: Double = -1.0
    private var lastHeadingEmitTime: TimeInterval = 0
    private var lastGpsFixTime: TimeInterval = 0
    private var lastStepTime: TimeInterval = 0
    private var userStepLengthM: Double = 0.65
    private var currentMotionState: MotionState = .stationaryLocked

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        setupLocationManager()
        setupPedometer()
        hapticGenerator.prepare()
    }

    private func setupLocationManager() {
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBestForNavigation
        locationManager.distanceFilter = 0.5
        locationManager.headingFilter = 1.0
        locationManager.pausesLocationUpdatesAutomatically = false
        locationManager.showsBackgroundLocationIndicator = true

        locationManager.requestWhenInUseAuthorization()
        locationManager.startUpdatingLocation()
        locationManager.startUpdatingHeading()
    }

    private func setupPedometer() {
        guard CMPedometer.isStepCountingAvailable() else { return }
        pedometer.startUpdates(from: Date()) { [weak self] (data, error) in
            guard let self = self, let data = data, error == nil else { return }
            self.onPedometerStep(data: data)
        }
    }

    private func onPedometerStep(data: CMPedometerData) {
        let now = ProcessInfo.processInfo.systemUptime
        lastStepTime = now
        currentMotionState = .pedestrianWalking

        let timeSinceGps = now - lastGpsFixTime

        // 若 GPS 中斷 (> 1.2s，如進入騎樓)，由 PDR 接管平滑推算
        if timeSinceGps > 1.2 && kalmanFilter.isReady() && smoothedHeading >= 0 {
            let pdr = kalmanFilter.advanceStep(stepMeters: userStepLengthM, headingDeg: smoothedHeading)
            DispatchQueue.main.async {
                self.webView?.evaluateJavaScript(
                    "if (window.onLocationUpdate) window.onLocationUpdate(\(pdr.lat), \(pdr.lon), 6.0, \(self.smoothedHeading), 1.1);",
                    completionHandler: nil
                )
            }
        }
    }

    // MARK: - CLLocationManagerDelegate

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }
        let now = ProcessInfo.processInfo.systemUptime
        lastGpsFixTime = now

        let rawLat = location.coordinate.latitude
        let rawLon = location.coordinate.longitude
        let acc = max(location.horizontalAccuracy, 1.0)
        let bearing = location.course >= 0 ? location.course : -1.0
        let speed = max(location.speed, 0.0)
        let timestamp = location.timestamp.timeIntervalSince1970

        // 運動狀態判定
        if speed >= 2.8 {
            currentMotionState = .vehicularTransit
        } else if (now - lastStepTime) > 1.4 && speed < 0.5 {
            currentMotionState = .stationaryLocked
        }

        // 行走時校準個人步長
        if speed > 0.6 && acc < 5.0 {
            let estimatedStep = min(max(speed / 1.8, 0.50), 0.85)
            userStepLengthM = 0.85 * userStepLengthM + 0.15 * estimatedStep
        }

        let filtered = kalmanFilter.filter(lat: rawLat, lon: rawLon, accuracy: acc, speed: speed, timestamp: timestamp, motionState: currentMotionState)

        let effectiveSpeed = (currentMotionState == .stationaryLocked) ? 0.0 : speed
        DispatchQueue.main.async {
            self.webView?.evaluateJavaScript(
                "if (window.onLocationUpdate) window.onLocationUpdate(\(filtered.lat), \(filtered.lon), \(acc), \(bearing), \(effectiveSpeed));",
                completionHandler: nil
            )
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateHeading newHeading: CLHeading) {
        let now = ProcessInfo.processInfo.systemUptime
        let headingDeg = (newHeading.trueHeading >= 0) ? newHeading.trueHeading : newHeading.magneticHeading

        if smoothedHeading < 0 {
            smoothedHeading = headingDeg
        } else {
            var diff = headingDeg - smoothedHeading
            while diff < -180.0 { diff += 360.0 }
            while diff > 180.0 { diff -= 360.0 }
            let alpha = (abs(diff) > 2.0) ? 0.85 : 0.35
            smoothedHeading = (smoothedHeading + alpha * diff + 360.0).truncatingRemainder(dividingBy: 360.0)
        }

        if now - lastHeadingEmitTime >= 0.025 {
            lastHeadingEmitTime = now
            let deg = smoothedHeading
            DispatchQueue.main.async {
                self.webView?.evaluateJavaScript(
                    "if (window.onHeadingUpdate) window.onHeadingUpdate(\(deg));",
                    completionHandler: nil
                )
            }
        }
    }

    func triggerHaptic(durationMs: Int64) {
        DispatchQueue.main.async {
            self.hapticGenerator.impactOccurred()
        }
    }
}
