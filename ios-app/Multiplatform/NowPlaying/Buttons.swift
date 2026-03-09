//
//  NowPlayingButtons.swift
//  Multiplatform
//
//  Created by Rasmus Krämer on 09.04.24.
//

import SwiftUI
import AmpFinKit
import AFPlayback
import AVKit

extension NowPlaying {
    static let showAirPlayPickerNotification = Notification.Name("NowPlaying.showAirPlayPicker")

    struct Buttons: View {
        @Environment(\.horizontalSizeClass) private var horizontalSizeClass
        @Environment(ViewModel.self) private var viewModel

        private var isCompact: Bool {
            horizontalSizeClass == .compact
        }

        @ViewBuilder private var lyricsButton: some View {
            Button {
                viewModel.selectTab(.lyrics)
            } label: {
                Label("lyrics", systemImage: viewModel.currentTab == .lyrics ? "text.bubble.fill" : "text.bubble")
                    .labelStyle(.iconOnly)
                    .foregroundStyle(viewModel.currentTab == .lyrics ? .thickMaterial : .thinMaterial)
                    .animation(.none, value: viewModel.currentTab)
                    .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .modifier(HoverEffectModifier(padding: 4))
            .padding(12)
            .onTapGesture {
                viewModel.selectTab(.lyrics)
            }
            .padding(-12)
            .disabled(true)
        }
        @ViewBuilder private var queueButton: some View {
            Menu {
                Toggle("shuffle", systemImage: "shuffle", isOn: .init(get: { viewModel.shuffled }, set: { AudioPlayer.current.shuffled = $0 }))

                Menu {
                    ForEach(RepeatMode.allCases.filter { AudioPlayer.current.infiniteQueue != nil || $0 != .infinite }) { repeatMode in
                        Toggle(isOn: .init(get: { viewModel.repeatMode == repeatMode }, set: { _ in AudioPlayer.current.repeatMode = repeatMode })) {
                            switch repeatMode {
                                case .none:
                                    Label("repeat.none", systemImage: "slash.circle")
                                case .queue:
                                    Label("repeat.queue", systemImage: "repeat")
                                case .track:
                                    Label("repeat.track", systemImage: "repeat.1")
                                case .infinite:
                                    Label("repeat.infinite", systemImage: "infinity")
                            }
                        }
                    }
                } label: {
                    Label("repeat", systemImage: "repeat")
                }
            } label: {
                Label("queue", systemImage: "list.dash")
                    .labelStyle(.iconOnly)
                    .contentShape(.rect)
            } primaryAction: {
                viewModel.selectTab(.queue)
            }
            .buttonStyle(SymbolButtonStyle(active: viewModel.currentTab == .queue))
            .modifier(HoverEffectModifier(padding: 4))
            .padding(12)
            .onTapGesture {
                viewModel.selectTab(.queue)
            }
            .padding(-12)
        }

        @ViewBuilder private var airPlayIcon: some View {
            Label("output", systemImage: viewModel.outputRoute.icon)
                .labelStyle(.iconOnly)
                .contentShape(.rect)
                .contentTransition(.symbolEffect(.replace.byLayer.downUp))
                .foregroundStyle(.thinMaterial)
                .modifier(HoverEffectModifier(padding: 4))
        }

        var body: some View {
            HStack(alignment: .center) {
                if viewModel.source == .local {
                    if isCompact {
                        Spacer()

                        lyricsButton
                            .frame(width: 75)

                        Spacer()

                        airPlayIcon
                            .frame(width: 75)
                            .overlay {
                                AirPlayRoutePickerOverlay()
                            }
                            .overlay(alignment: .bottom) {
                                if viewModel.outputRoute.showLabel {
                                    Text(viewModel.outputRoute.name)
                                        .lineLimit(1)
                                        .font(.caption2.smallCaps())
                                        .foregroundStyle(.thinMaterial)
                                        .offset(y: 12)
                                        .fixedSize()
                                }
                            }

                        Spacer()

                        queueButton
                            .frame(width: 75)

                        Spacer()
                    } else if horizontalSizeClass == .regular {
                        HStack(spacing: 4) {
                            Button {
                                NotificationCenter.default.post(name: NowPlaying.showAirPlayPickerNotification, object: nil)
                            } label: {
                                airPlayIcon
                            }
                            .buttonStyle(.plain)

                            if viewModel.outputRoute.showLabel {
                                Text(viewModel.outputRoute.name)
                                    .lineLimit(1)
                                    .font(.caption.smallCaps())
                                    .foregroundStyle(.thinMaterial)
                            }
                        }

                        Spacer()

                        lyricsButton
                            .padding(.horizontal, 16)
                        queueButton
                    }
                } else if viewModel.source == .jellyfinRemote {
                    Spacer()

                    lyricsButton

                    Spacer()

                    Button {
                        AudioPlayer.current.shuffled.toggle()
                    } label: {
                        Label("shuffle", systemImage: "shuffle")
                            .labelStyle(.iconOnly)
                            .contentShape(.rect)
                    }
                    .buttonStyle(SymbolButtonStyle(active: viewModel.shuffled))
                    .padding(12)
                    .onTapGesture {
                        AudioPlayer.current.shuffled.toggle()
                    }
                    .padding(-12)

                    Spacer()

                    Button {
                        AudioPlayer.current.repeatMode = viewModel.repeatMode.next
                    } label: {
                        Label("repeat", systemImage: "repeat\(viewModel.repeatMode == .track ? ".1" : "")")
                            .labelStyle(.iconOnly)
                            .contentShape(.rect)
                    }
                    .buttonStyle(SymbolButtonStyle(active: viewModel.repeatMode != .none))
                    .padding(12)
                    .onTapGesture {
                        AudioPlayer.current.repeatMode = viewModel.repeatMode.next
                    }
                    .padding(-12)

                    Spacer()
                }
            }
            .bold()
            .font(.system(size: 20))
        }
    }
}

/// Transparent overlay that directly embeds an AVRoutePickerView for compact layout (no fullScreenCover).
private struct AirPlayRoutePickerOverlay: UIViewRepresentable {
    func makeUIView(context: Context) -> AVRoutePickerView {
        let picker = AVRoutePickerView()
        picker.tintColor = UIColor(white: 1, alpha: 0.005)
        picker.activeTintColor = UIColor(white: 1, alpha: 0.005)
        return picker
    }

    func updateUIView(_ uiView: AVRoutePickerView, context: Context) {}
}
