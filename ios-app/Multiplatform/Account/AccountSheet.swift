//
//  AccountSheet.swift
//  AmpFin
//
//  Account settings for 24six.
//

import SwiftUI
import TipKit
import Nuke
import AmpFinKit

internal struct AccountSheet: View {
    @Environment(\.dismiss) private var dismiss

    @State private var downloads: [Track]? = nil

    var body: some View {
        NavigationStack {
            List {
                HStack(spacing: 0) {
                    Image(systemName: "person.crop.circle.fill")
                        .font(.system(size: 44))
                        .foregroundStyle(.secondary)

                    VStack(alignment: .leading, spacing: 4) {
                        Text("24six Account")
                            .font(.headline)

                        Text(TwentyFourSixClient.shared._email ?? "")
                            .font(.caption)
                            .fontDesign(.monospaced)
                    }
                    .padding(.leading, 16)
                }

                Section {
                    Button {
                        UIApplication.shared.open(URL(string: UIApplication.openSettingsURLString)!)
                    } label: {
                        Label("account.settings", systemImage: "gear")
                    }
                }
                .foregroundStyle(.primary)

                Section("account.downloads.queue") {
                    if let downloads = downloads {
                        if downloads.isEmpty {
                            Text("account.downloads.queue.empty")
                                .foregroundStyle(.secondary)
                        } else {
                            ForEach(downloads) {
                                TrackListRow(track: $0, preview: true) {}
                            }
                        }
                    } else {
                        ProgressView()
                            .onAppear {
                                downloads = try? OfflineManager.shared.downloading()
                            }
                    }
                }

                Section {
                    Button {
                        UIApplication.shared.open(URL(string: "https://github.com/rasmuslos/AmpFin")!)
                    } label: {
                        Label("account.github", systemImage: "chevron.left.forwardslash.chevron.right")
                    }

                    Button {
                        UIApplication.shared.open(URL(string: "https://rfk.io/support.htm")!)
                    } label: {
                        Label("account.support", systemImage: "lifepreserver")
                    }
                }
                .foregroundStyle(.primary)

                Section {
                    Button(role: .destructive) {
                        TwentyFourSixClient.shared.logout()
                    } label: {
                        Label("account.logout", systemImage: "person.crop.circle.badge.minus")
                    }

                    Button(role: .destructive) {
                        SpotlightHelper.deleteSpotlightIndex()
                        ImagePipeline.shared.cache.removeAll()
                    } label: {
                        Label("account.deleteSpotlightIndex", systemImage: "square.stack.3d.up.slash")
                    }

                    Button(role: .destructive) {
                        try! OfflineManager.shared.delete()
                    } label: {
                        Label("account.deleteDownloads", systemImage: "slash.circle")
                    }
                }
                .foregroundStyle(.red)

                Section("account.server") {
                    Group {
                        Text("24six API v3")

                        Text(TwentyFourSixClient.shared.deviceId)
                        Text(TwentyFourSixClient.shared.token)
                            .privacySensitive()
                    }
                    .font(.footnote)
                    .fontDesign(.monospaced)
                    .foregroundStyle(.secondary)
                }

                Section("account.app") {
                    Text("account.version.app \(TwentyFourSixClient.shared.clientVersion) \(TwentyFourSixClient.shared.clientBuild)")
                    Text("account.version.database \(PersistenceManager.shared.modelContainer.schema.version.description) \(PersistenceManager.shared.modelContainer.configurations.map { $0.name }.joined(separator: ", "))")
                }
                .font(.footnote)
                .foregroundStyle(.secondary)
            }
            .navigationTitle("account.title")
            .navigationBarTitleDisplayMode(.inline)
            #if targetEnvironment(macCatalyst) || os(visionOS)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        dismiss()
                    } label: {
                        Text("done")
                    }
                }
            }
            #endif
        }
    }
}

internal struct AccountToolbarButtonModifier: ViewModifier {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    @State private var accountSheetPresented = false

    let requiredSize: UserInterfaceSizeClass?

    func body(content: Content) -> some View {
        if requiredSize == nil || horizontalSizeClass == requiredSize {
            content
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            accountSheetPresented.toggle()
                        } label: {
                            Label("account", systemImage: "person.crop.circle")
                                .labelStyle(.iconOnly)
                        }
                    }
                }
                .sheet(isPresented: $accountSheetPresented) {
                    AccountSheet()
                }
        } else {
            content
        }
    }
}


#Preview {
    Text(verbatim: ":)")
        .sheet(isPresented: .constant(true)) {
            AccountSheet()
        }
}
