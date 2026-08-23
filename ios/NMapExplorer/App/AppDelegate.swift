/**
 * iOS 應用程式入口生命週期管理器 (iOS Application Lifecycle Delegate)
 * 
 * 作用：
 * 1. 設置 AVAudioSession 為 .playback 模式，並開啟 .mixWithOthers 與藍牙耳機支援 (.allowBluetooth, .allowBluetoothA2DP)。
 * 2. 確保視障者使用骨傳導耳機或藍牙耳機時，Web Audio 3D 空間音效與 VoiceOver 朗讀聲音能無縫共存、不被系統中斷。
 * 3. 初始化主畫面 UIWindow 並掛載 ViewController。
 */
import UIKit
import AVFoundation

@main
class AppDelegate: UIResponder, UIApplicationDelegate {

    var window: UIWindow?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        // 配置後台音訊工作階段，支援無障礙藍牙耳機混音與 3D 空間音效
        do {
            try AVAudioSession.sharedInstance().setCategory(
                .playback,
                mode: .default,
                options: [.mixWithOthers, .allowBluetooth, .allowBluetoothA2DP]
            )
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            print("Failed to set audio session category: \(error)")
        }

        window = UIWindow(frame: UIScreen.main.bounds)
        window?.rootViewController = ViewController()
        window?.makeKeyAndVisible()

        return true
    }
}

