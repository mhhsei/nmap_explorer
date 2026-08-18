import UIKit
import WebKit

class ViewController: UIViewController, WKScriptMessageHandler, WKNavigationDelegate {

    private var webView: WKWebView!
    private var sensorBridge: LocationSensorBridge?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 15/255.0, green: 23/255.0, blue: 42/255.0, alpha: 1.0) // #0f172a

        setupWebView()
        sensorBridge = LocationSensorBridge(webView: webView)
        loadWebContent()
    }

    private func setupWebView() {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []

        let userContentController = WKUserContentController()

        // JS Compatibility Bridge: intercept AndroidBridge calls and forward to iOS native handler
        let bridgeScriptSource = """
        window.AndroidBridge = {
            vibrate: function(ms) {
                window.webkit.messageHandlers.iOSBridge.postMessage({ action: 'vibrate', duration: ms });
            },
            shareAppLogs: function() {
                window.webkit.messageHandlers.iOSBridge.postMessage({ action: 'shareLogs' });
            }
        };
        """
        let userScript = WKUserScript(source: bridgeScriptSource, injectionTime: .atDocumentStart, forMainFrameOnly: false)
        userContentController.addUserScript(userScript)
        userContentController.add(self, name: "iOSBridge")
        config.userContentController = userContentController

        webView = WKWebView(frame: .zero, configuration: config)
        webView.translatesAutoresizingMaskIntoConstraints = false
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        webView.navigationDelegate = self

        view.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            webView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            webView.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor)
        ])
    }

    private func loadWebContent() {
        if let wwwURL = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "www") {
            let readAccessURL = wwwURL.deletingLastPathComponent()
            webView.loadFileURL(wwwURL, allowingReadAccessTo: readAccessURL)
        } else if let indexURL = Bundle.main.url(forResource: "index", withExtension: "html") {
            webView.loadFileURL(indexURL, allowingReadAccessTo: indexURL.deletingLastPathComponent())
        } else {
            // Fallback to local server or error page
            let html = "<h1 style='color:white;text-align:center;margin-top:50px;'>NMap Explorer iOS 載入中...</h1>"
            webView.loadHTMLString(html, baseURL: nil)
        }
    }

    // MARK: - WKScriptMessageHandler

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "iOSBridge", let body = message.body as? [String: Any] else { return }
        let action = body["action"] as? String ?? ""

        switch action {
        case "vibrate":
            let duration = (body["duration"] as? NSNumber)?.int64Value ?? 50
            sensorBridge?.triggerHaptic(durationMs: duration)

        case "shareLogs":
            shareDiagnosticLogs()

        case "getOverpassCache":
            let queryKey = body["queryKey"] as? String ?? ""
            let callbackId = body["callbackId"] as? String ?? ""
            DatabaseManager.shared.getOverpass(queryKey: queryKey) { resultJson in
                DispatchQueue.main.async {
                    let escaped = (resultJson ?? "").replacingOccurrences(of: "\\", with: "\\\\")
                                                    .replacingOccurrences(of: "\"", with: "\\\"")
                                                    .replacingOccurrences(of: "\n", with: "\\n")
                    self.webView.evaluateJavaScript("if (window.onDatabaseResult) window.onDatabaseResult('\(callbackId)', \"\(escaped)\");", completionHandler: nil)
                }
            }

        case "setOverpassCache":
            let queryKey = body["queryKey"] as? String ?? ""
            let dataJson = body["dataJson"] as? String ?? ""
            DatabaseManager.shared.setOverpass(queryKey: queryKey, dataJson: dataJson)

        case "queryOverturePlaces":
            let lat = (body["lat"] as? NSNumber)?.doubleValue ?? 0.0
            let lon = (body["lon"] as? NSNumber)?.doubleValue ?? 0.0
            let radius = (body["radius"] as? NSNumber)?.doubleValue ?? 60.0
            let callbackId = body["callbackId"] as? String ?? ""

            DatabaseManager.shared.queryNearbyOverturePlaces(lat: lat, lon: lon, radiusM: radius) { places in
                if let jsonData = try? JSONSerialization.data(withJSONObject: places, options: []),
                   let jsonStr = String(data: jsonData, encoding: .utf8) {
                    DispatchQueue.main.async {
                        let escaped = jsonStr.replacingOccurrences(of: "\\", with: "\\\\")
                                             .replacingOccurrences(of: "\"", with: "\\\"")
                                             .replacingOccurrences(of: "\n", with: "\\n")
                        self.webView.evaluateJavaScript("if (window.onDatabaseResult) window.onDatabaseResult('\(callbackId)', \"\(escaped)\");", completionHandler: nil)
                    }
                }
            }

        default:
            break
        }
    }

    private func shareDiagnosticLogs() {
        let timeStr = ISO8601DateFormatter().string(from: Date())
        let devInfo = """
        【NMap Explorer iOS 診斷資訊】
        時間: \(timeStr)
        系統: iOS \(UIDevice.current.systemVersion)
        裝置: \(UIDevice.current.model)
        """

        let tempFile = FileManager.default.temporaryDirectory.appendingPathComponent("nmap_ios_diag.txt")
        try? devInfo.write(to: tempFile, atomically: true, encoding: .utf8)

        let activityVC = UIActivityViewController(activityItems: [tempFile], applicationActivities: nil)
        if let popover = activityVC.popoverPresentationController {
            popover.sourceView = view
            popover.sourceRect = CGRect(x: view.bounds.midX, y: view.bounds.midY, width: 0, height: 0)
        }
        present(activityVC, animated: true)
    }

    override var preferredStatusBarStyle: UIStatusBarStyle {
        return .lightContent
    }
}
