//
//  MusicApp.swift
//  Music
//
//  Created by Rasmus Krämer on 05.09.23.
//

import SwiftUI
import Nuke
import Defaults
import AmpFinKit
import AFPlayback

@main
struct MultiplatformApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @State private var nowPlayingViewModel = NowPlaying.ViewModel()

    init() {
        #if !ENABLE_ALL_FEATURES
        AFKIT_ENABLE_ALL_FEATURES = false
        #endif

        // Derive app group from bundle ID (e.g. tk.mordy.ampfin -> group.tk.mordy.ampfin)
        if let bundleId = Bundle.main.bundleIdentifier {
            AFKIT_APP_GROUP = "group.\(bundleId)"
        }

        ImagePipeline.shared = ImagePipeline(configuration: .withDataCache)
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(nowPlayingViewModel)
                #if targetEnvironment(macCatalyst)
                .onAppear {
                    UIApplication.shared.connectedScenes
                        .compactMap { $0 as? UIWindowScene }
                        .forEach { $0.titlebar?.titleVisibility = .hidden }
                }
                #endif
        }
        .modelContainer(PersistenceManager.shared.modelContainer)
    }
}
