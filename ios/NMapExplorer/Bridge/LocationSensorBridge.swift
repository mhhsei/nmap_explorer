/**
 * iOS 定位與感測器橋接器 (iOS Location & Sensor Bridge)
 * 
 * 作用：
 * 1. 2D 行人卡爾曼濾波器 (Pedestrian Kalman Filter)：
 *    濾除高樓大廈多路徑效應造成的 GPS 漂移跳動，並在進入騎樓遮蔽時，無縫切換為 CMPedometer 行人慣性推算 (PDR)。
 * 2. 磁北與真北即時平滑：透過 20Hz (0.05s) 低通濾波將指北針角度推送給 WebView 前端。
 * 3. 觸覺震動回饋 (UIImpactFeedbackGenerator)：在撞牆或到達路口時觸發觸覺震動。
 */
import Foundation
import CoreLocation
import CoreMotion
import WebKit
import UIKit

/**
 * 2D 行人卡爾曼濾波器 (2D Pedestrian Kalman Filter)
 */
class PedestrianKalmanFilter {
    private var isInitialized = false
    private var anchorLat: Double = 0.0
    private var anchorLon: Double = 0.0

    private var x: Double = 0.0
    private var y: Double = 0.0
    private var vx: Double = 0.0
    private var vy: Double = 0.0

    private var p00: Double = 10.0
    private var p11: Double = 10.0
    private var p22: Double = 2.0
    private var p33: Double = 2.0

    private var lastTimestamp: TimeInterval = 0

    func filter(lat: Double, lon: Double, accuracy: Double, timestamp: TimeInterval) -> (lat: Double, lon: Double) {

        if !isInitialized {
            anchorLat = lat
            anchorLon = lon
            x = 0.0
            y = 0.0
            vx = 0.0
            vy = 0.0
            lastTimestamp = timestamp
            isInitialized = true
            return (lat, lon)
        }

        var dt = timestamp - lastTimestamp
        lastTimestamp = timestamp
        if dt <= 0.0 || dt > 10.0 { dt = 1.0 }

        let radLat = anchorLat * .pi / 180.0
        let mPerLat = 111139.0
        let mPerLon = 111139.0 * cos(radLat)

        let zx = (lon - anchorLon) * mPerLon
        let zy = (lat - anchorLat) * mPerLat

        x += vx * dt
        y += vy * dt

        let qPos = 0.5 * dt
        let qVel = 1.0 * dt
        p00 += p22 * dt * dt + qPos
        p11 += p33 * dt * dt + qPos
        p22 += qVel
        p33 += qVel

        let measuredDelta = sqrt(pow(zx - x, 2) + pow(zy - y, 2))
        let impliedSpeed = measuredDelta / dt
        let baseR = max(pow(accuracy, 2), 4.0)
        let r = (impliedSpeed > 4.5) ? baseR * 10.0 : baseR

        let k0 = p00 / (p00 + r)
        let k1 = p11 / (p11 + r)

        x += k0 * (zx - x)
        y += k1 * (zy - y)

        p00 *= (1.0 - k0)
        p11 *= (1.0 - k1)

        vx = (k0 * (zx - x)) / dt
        vy = (k1 * (zy - y)) / dt

        let currentSpeed = sqrt(vx * vx + vy * vy)
        if currentSpeed > 4.5 {
            let scale = 4.5 / currentSpeed
            vx *= scale
            vy *= scale
        } else if currentSpeed < 0.25 {
            vx = 0.0
            vy = 0.0
        }

        let outLat = anchorLat + (y / mPerLat)
        let outLon = anchorLon + (x / mPerLon)
        return (outLat, outLon)
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

        let radLat = anchorLat * .pi / 180.0
        let mPerLat = 111139.0
        let mPerLon = 111139.0 * cos(radLat)

        let outLat = anchorLat + (y / mPerLat)
        let outLon = anchorLon + (x / mPerLon)
        return (outLat, outLon)
    }

    func isReady() -> Bool {
        return isInitialized
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
    private var userStepLengthM: Double = 0.65

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
        let timeSinceGps = now - lastGpsFixTime

        // If GPS is obscured (> 1.2s without update, e.g. under arcade / 騎樓), advance via PDR
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
        lastGpsFixTime = ProcessInfo.processInfo.systemUptime

        let rawLat = location.coordinate.latitude
        let rawLon = location.coordinate.longitude
        let acc = max(location.horizontalAccuracy, 1.0)
        let bearing = location.course >= 0 ? location.course : -1.0
        let speed = max(location.speed, 0.0)
        let timestamp = location.timestamp.timeIntervalSince1970

        // Auto-calibrate step length on clear GPS walk
        if speed > 0.6 && acc < 5.0 {
            let estimatedStep = min(max(speed / 1.8, 0.50), 0.85)
            userStepLengthM = 0.85 * userStepLengthM + 0.15 * estimatedStep
        }

        let filtered = kalmanFilter.filter(lat: rawLat, lon: rawLon, accuracy: acc, timestamp: timestamp)

        DispatchQueue.main.async {
            self.webView?.evaluateJavaScript(
                "if (window.onLocationUpdate) window.onLocationUpdate(\(filtered.lat), \(filtered.lon), \(acc), \(bearing), \(speed));",
                completionHandler: nil
            )
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateHeading newHeading: CLHeading) {
        let now = ProcessInfo.processInfo.systemUptime
        // True North is automatically calculated by iOS CoreLocation
        let headingDeg = (newHeading.trueHeading >= 0) ? newHeading.trueHeading : newHeading.magneticHeading

        if smoothedHeading < 0 {
            smoothedHeading = headingDeg
        } else {
            var diff = headingDeg - smoothedHeading
            while diff < -180.0 { diff += 360.0 }
            while diff > 180.0 { diff -= 360.0 }
            smoothedHeading = (smoothedHeading + 0.30 * diff + 360.0).truncatingRemainder(dividingBy: 360.0)
        }

        if now - lastHeadingEmitTime >= 0.05 {
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
