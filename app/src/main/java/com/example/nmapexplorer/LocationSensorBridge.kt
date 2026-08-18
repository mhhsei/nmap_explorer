package com.example.nmapexplorer

import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.GeomagneticField
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.GnssStatus
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.webkit.WebView
import androidx.core.content.ContextCompat
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import kotlin.math.*

/**
 * 2D Pedestrian Kalman Filter with Adaptive Noise Covariance, Zero-Velocity Update (ZUPT),
 * Urban Canyon Multipath Rejection, and Pedestrian Dead Reckoning (PDR) step propagation.
 */
class PedestrianKalmanFilter {
    private var isInitialized = false
    private var anchorLat = 0.0
    private var anchorLon = 0.0

    // State: [x (m), y (m), vx (m/s), vy (m/s)]
    private var x = 0.0
    private var y = 0.0
    private var vx = 0.0
    private var vy = 0.0

    // Covariance matrix 4x4 (diagonal approx)
    private var p00 = 10.0 // var x
    private var p11 = 10.0 // var y
    private var p22 = 2.0  // var vx
    private var p33 = 2.0  // var vy

    private var lastTimestampNanos: Long = 0

    fun filter(
        lat: Double,
        lon: Double,
        accuracyMeters: Float,
        timestampNanos: Long,
        isMultipath: Boolean = false
    ): Pair<Double, Double> {
        if (!isInitialized) {
            anchorLat = lat
            anchorLon = lon
            x = 0.0
            y = 0.0
            vx = 0.0
            vy = 0.0
            lastTimestampNanos = timestampNanos
            isInitialized = true
            return Pair(lat, lon)
        }

        var dt = (timestampNanos - lastTimestampNanos) / 1_000_000_000.0
        lastTimestampNanos = timestampNanos

        if (dt <= 0.0 || dt > 10.0) {
            dt = 1.0
        }

        // 1. Convert new measurement to local meters (equirectangular projection)
        val radLat = Math.toRadians(anchorLat)
        val mPerLat = 111139.0
        val mPerLon = 111139.0 * cos(radLat)

        val zx = (lon - anchorLon) * mPerLon
        val zy = (lat - anchorLat) * mPerLat

        // 2. Predict Step
        x += vx * dt
        y += vy * dt

        val qPos = 0.5 * dt // process noise position
        val qVel = 1.0 * dt // process noise velocity
        p00 += p22 * dt * dt + qPos
        p11 += p33 * dt * dt + qPos
        p22 += qVel
        p33 += qVel

        // 3. Measurement Update with Adaptive Noise Covariance R
        val measuredDelta = sqrt((zx - x).pow(2.0) + (zy - y).pow(2.0))
        val impliedSpeed = measuredDelta / dt

        // Base R derived from GPS accuracy
        var baseR = max(accuracyMeters.toDouble().pow(2.0), 4.0)

        // Urban Canyon Multipath Rejection (Item 3)
        if (isMultipath) {
            baseR *= 6.0
        }
        val r = if (impliedSpeed > 4.5) baseR * 10.0 else baseR

        val k0 = p00 / (p00 + r)
        val k1 = p11 / (p11 + r)

        x += k0 * (zx - x)
        y += k1 * (zy - y)

        p00 *= (1.0 - k0)
        p11 *= (1.0 - k1)

        // Update velocity estimate
        vx = (k0 * (zx - x)) / dt
        vy = (k1 * (zy - y)) / dt

        // Clamp pedestrian speed (max 4.5 m/s)
        val currentSpeed = sqrt(vx * vx + vy * vy)
        if (currentSpeed > 4.5) {
            val scale = 4.5 / currentSpeed
            vx *= scale
            vy *= scale
        } else if (currentSpeed < 0.25) {
            // Zero-Velocity Update (ZUPT): Stationary lock to eliminate stationary GPS drift
            vx = 0.0
            vy = 0.0
        }

        // 4. Convert back to Lat/Lon
        val outLat = anchorLat + (y / mPerLat)
        val outLon = anchorLon + (x / mPerLon)

        return Pair(outLat, outLon)
    }

    /**
     * Pedestrian Dead Reckoning (PDR) step advance when GPS is obscured (Item 2: 騎樓步伐推算).
     */
    fun advanceStep(stepMeters: Double, headingDeg: Double): Pair<Double, Double> {
        if (!isInitialized) return Pair(anchorLat, anchorLon)
        val radHead = Math.toRadians(headingDeg)
        val dx = stepMeters * sin(radHead)
        val dy = stepMeters * cos(radHead)

        x += dx
        y += dy
        vx = dx / 0.6 // assume ~0.6s step interval
        vy = dy / 0.6

        val radLat = Math.toRadians(anchorLat)
        val mPerLat = 111139.0
        val mPerLon = 111139.0 * cos(radLat)

        val outLat = anchorLat + (y / mPerLat)
        val outLon = anchorLon + (x / mPerLon)
        return Pair(outLat, outLon)
    }

    fun isFilterInitialized(): Boolean = isInitialized

    fun reset() {
        isInitialized = false
    }
}

class LocationSensorBridge(private val context: Context, private val webView: WebView) : SensorEventListener, LocationListener {

    private val tag = "LocationSensorBridge"
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val locationManager = context.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
    private val fusedLocationClient: FusedLocationProviderClient = LocationServices.getFusedLocationProviderClient(context)

    private val rotationMatrix = FloatArray(9)
    private val orientationAngles = FloatArray(3)
    private val accelerometerReading = FloatArray(3)
    private val magnetometerReading = FloatArray(3)

    private var hasRotationVector = false
    private var smoothedHeading = -1f
    private var lastHeadingEmitTime = 0L

    // Item 4: Geomagnetic Declination for True North correction (Taiwan default ~ -3.8°)
    private var geomagneticDeclination: Float = -3.8f

    // Item 3: GNSS Status & Multipath detection
    private var gnssStatusCallback: GnssStatus.Callback? = null
    private var isUrbanCanyonMultipath = false

    // Item 2: PDR Step Detector & step length auto-calibration
    private var userStepLengthM = 0.65f
    private var lastGpsFixTimeMs = 0L
    private var lastStepEmitTimeMs = 0L
    private var stepDetectorSensor: Sensor? = null

    private val kalmanFilter = PedestrianKalmanFilter()
    private var isRunning = false
    private var lastEmittedLocation: Location? = null

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(locationResult: LocationResult) {
            for (location in locationResult.locations) {
                onLocationChanged(location)
            }
        }
    }

    @SuppressLint("MissingPermission")
    fun start() {
        if (isRunning) return
        isRunning = true
        Log.i(tag, "Starting sensors with 9-axis fusion, True North correction, GNSS SNR filtering, and PDR...")

        // 1. Prioritize TYPE_ROTATION_VECTOR for jitter-free orientation
        val rotVectorSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
        if (rotVectorSensor != null) {
            hasRotationVector = true
            sensorManager.registerListener(this, rotVectorSensor, SensorManager.SENSOR_DELAY_GAME)
            Log.i(tag, "Using hardware 9-axis TYPE_ROTATION_VECTOR for responsive heading.")
        } else {
            hasRotationVector = false
            sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.also {
                sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
            }
            sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)?.also {
                sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
            }
            Log.i(tag, "Fallback to Accelerometer + Magnetometer.")
        }

        // 2. Register Step Detector for PDR under covered arcades (Item 2)
        stepDetectorSensor = sensorManager.getDefaultSensor(Sensor.TYPE_STEP_DETECTOR)
        if (stepDetectorSensor != null) {
            sensorManager.registerListener(this, stepDetectorSensor, SensorManager.SENSOR_DELAY_FASTEST)
            Log.i(tag, "Using hardware STEP_DETECTOR for arcade PDR navigation.")
        }

        // 3. Register GNSS Status Callback for satellite SNR & Multipath filtering (Item 3)
        registerGnssStatusCallback()

        val hasFine = ContextCompat.checkSelfPermission(context, android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(context, android.Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

        if (!hasFine && !hasCoarse) {
            Log.w(tag, "Location permissions not granted yet, sensors started but GPS waiting.")
            return
        }

        try {
            // Google Play Services Fused Location
            val locationRequest = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 1000L)
                .setMinUpdateIntervalMillis(500L)
                .setMinUpdateDistanceMeters(0.5f)
                .build()

            fusedLocationClient.requestLocationUpdates(
                locationRequest,
                locationCallback,
                Looper.getMainLooper()
            )

            // Check if lastLocation is fresh (< 30 seconds)
            fusedLocationClient.lastLocation.addOnSuccessListener { location: Location? ->
                location?.let {
                    val ageNanos = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR1) {
                        SystemClock.elapsedRealtimeNanos() - it.elapsedRealtimeNanos
                    } else {
                        (System.currentTimeMillis() - it.time) * 1_000_000L
                    }
                    if (ageNanos < 30_000_000_000L) {
                        Log.i(tag, "Using fresh lastLocation: ${it.latitude}, ${it.longitude}")
                        onLocationChanged(it)
                    } else {
                        Log.i(tag, "Ignoring stale lastLocation (${ageNanos / 1_000_000_000L}s old).")
                    }
                }
            }

            // Fallback native LocationManager
            locationManager?.let { lm ->
                if (lm.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                    lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0.5f, this, Looper.getMainLooper())
                }
                if (lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
                    lm.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, 1000L, 0.5f, this, Looper.getMainLooper())
                }
            }
        } catch (e: SecurityException) {
            Log.e(tag, "SecurityException while requesting location updates", e)
        }
    }

    @SuppressLint("MissingPermission")
    private fun registerGnssStatusCallback() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N && locationManager != null) {
            try {
                gnssStatusCallback = object : GnssStatus.Callback() {
                    override fun onSatelliteStatusChanged(status: GnssStatus) {
                        val count = status.satelliteCount
                        var highCount = 0
                        var totalSnr = 0f
                        var usedCount = 0
                        for (i in 0 until count) {
                            val snr = status.getCn0DbHz(i)
                            if (status.usedInFix(i)) {
                                usedCount++
                                totalSnr += snr
                                if (snr >= 22.0f) {
                                    highCount++
                                }
                            }
                        }
                        val avgSnr = if (usedCount > 0) totalSnr / usedCount else 0f
                        // Multipath detection: If used satellites have very low SNR (< 21 dB-Hz), urban canyon reflection is high
                        isUrbanCanyonMultipath = (usedCount >= 3 && avgSnr < 21.0f) || (highCount < 4 && usedCount >= 4)
                    }
                }
                locationManager.registerGnssStatusCallback(gnssStatusCallback!!, Handler(Looper.getMainLooper()))
                Log.i(tag, "GnssStatusCallback registered for urban canyon multipath filtering.")
            } catch (e: Exception) {
                Log.w(tag, "Could not register GnssStatusCallback: ${e.message}")
            }
        }
    }

    fun stop() {
        isRunning = false
        sensorManager.unregisterListener(this)
        kalmanFilter.reset()
        try {
            fusedLocationClient.removeLocationUpdates(locationCallback)
            locationManager?.removeUpdates(this)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N && gnssStatusCallback != null) {
                locationManager?.unregisterGnssStatusCallback(gnssStatusCallback!!)
            }
        } catch (e: Exception) {
            Log.e(tag, "Error stopping location updates", e)
        }
    }

    private fun updateGeomagneticDeclination(lat: Double, lon: Double, alt: Double) {
        try {
            val geoField = GeomagneticField(
                lat.toFloat(),
                lon.toFloat(),
                alt.toFloat(),
                System.currentTimeMillis()
            )
            geomagneticDeclination = geoField.declination
        } catch (e: Exception) {
            Log.w(tag, "GeomagneticField fallback", e)
        }
    }

    private fun onStepDetected() {
        val now = SystemClock.uptimeMillis()
        if (now - lastStepEmitTimeMs < 250L) return
        lastStepEmitTimeMs = now

        // Item 2: If GPS is obscured (> 1200ms without update, e.g. under arcade / 騎樓), advance smoothly via PDR
        val timeSinceGps = now - lastGpsFixTimeMs
        if (timeSinceGps > 1200L && kalmanFilter.isFilterInitialized() && smoothedHeading >= 0f) {
            val (pdrLat, pdrLon) = kalmanFilter.advanceStep(userStepLengthM.toDouble(), smoothedHeading.toDouble())
            Log.d(tag, "PDR Step Advance under arcade: ($pdrLat, $pdrLon) Step: ${userStepLengthM}m Heading: $smoothedHeading")
            webView.post {
                webView.evaluateJavascript(
                    "if (window.onLocationUpdate) window.onLocationUpdate(${pdrLat}, ${pdrLon}, 6.0, ${smoothedHeading}, 1.1);",
                    null
                )
            }
        }
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type == Sensor.TYPE_STEP_DETECTOR) {
            onStepDetected()
            return
        }

        val now = SystemClock.uptimeMillis()

        if (event.sensor.type == Sensor.TYPE_ROTATION_VECTOR) {
            SensorManager.getRotationMatrixFromVector(rotationMatrix, event.values)
        } else if (event.sensor.type == Sensor.TYPE_ACCELEROMETER) {
            System.arraycopy(event.values, 0, accelerometerReading, 0, accelerometerReading.size)
            SensorManager.getRotationMatrix(rotationMatrix, null, accelerometerReading, magnetometerReading)
        } else if (event.sensor.type == Sensor.TYPE_MAGNETIC_FIELD) {
            System.arraycopy(event.values, 0, magnetometerReading, 0, magnetometerReading.size)
            SensorManager.getRotationMatrix(rotationMatrix, null, accelerometerReading, magnetometerReading)
        } else {
            return
        }

        SensorManager.getOrientation(rotationMatrix, orientationAngles)
        val rawDegrees = ((Math.toDegrees(orientationAngles[0].toDouble()) + 360.0) % 360.0).toFloat()

        // Item 4: True North correction (Geomagnetic Declination)
        val trueDegrees = ((rawDegrees + geomagneticDeclination + 360.0f) % 360.0f)

        if (smoothedHeading < 0f) {
            smoothedHeading = trueDegrees
        } else {
            // Circular smoothing with shortest path
            var diff = trueDegrees - smoothedHeading
            while (diff < -180f) diff += 360f
            while (diff > 180f) diff -= 360f
            smoothedHeading = (smoothedHeading + 0.30f * diff + 360f) % 360f
        }

        // Throttle emission to WebView (every 50ms) to ensure instant, fluid response without lag
        if (now - lastHeadingEmitTime >= 50L) {
            lastHeadingEmitTime = now
            val deg = smoothedHeading
            webView.post {
                webView.evaluateJavascript("if (window.onHeadingUpdate) window.onHeadingUpdate(${deg});", null)
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    override fun onLocationChanged(location: Location) {
        lastGpsFixTimeMs = SystemClock.uptimeMillis()

        // Discard extreme low accuracy fixes (> 50m) if already fixed
        if (location.hasAccuracy() && location.accuracy > 50f && lastEmittedLocation != null) {
            return
        }

        lastEmittedLocation = location
        val rawLat = location.latitude
        val rawLon = location.longitude
        val acc = if (location.hasAccuracy()) location.accuracy else 10f
        val bearing = if (location.hasBearing()) location.bearing else -1f
        val speed = if (location.hasSpeed()) location.speed else 0f
        val timestampNanos = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR1) {
            location.elapsedRealtimeNanos
        } else {
            System.currentTimeMillis() * 1_000_000L
        }

        // Item 4: Update Geomagnetic Field at new GPS fix
        val alt = if (location.hasAltitude()) location.altitude else 0.0
        updateGeomagneticDeclination(rawLat, rawLon, alt)

        // Item 2: Auto-calibrate user step length when walking with high GPS accuracy
        if (location.hasSpeed() && speed > 0.6f && location.hasAccuracy() && acc < 5.0f) {
            val estimatedStep = (speed / 1.8f).coerceIn(0.50f, 0.85f)
            userStepLengthM = 0.85f * userStepLengthM + 0.15f * estimatedStep
        }

        // Apply Pedestrian Kalman Filter with Urban Canyon Multipath Rejection (Item 3)
        val (filteredLat, filteredLon) = kalmanFilter.filter(
            rawLat, rawLon, acc, timestampNanos, isUrbanCanyonMultipath
        )

        Log.d(tag, "GPS (Raw: $rawLat, $rawLon) -> (Kalman: $filteredLat, $filteredLon) Acc: $acc Multipath: $isUrbanCanyonMultipath")

        webView.post {
            webView.evaluateJavascript(
                "if (window.onLocationUpdate) window.onLocationUpdate(${filteredLat}, ${filteredLon}, ${acc}, ${bearing}, ${speed});",
                null
            )
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
}
