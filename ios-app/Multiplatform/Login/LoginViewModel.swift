//
//  LoginViewModel.swift
//  AmpFin
//
//  Login flow for 24six: email -> profiles -> credentials -> login.
//

import Foundation
import SwiftUI
import AmpFinKit

extension LoginView {
    @Observable
    final class LoginViewModel {
        @MainActor var sheetPresented: Bool
        @MainActor var flowStep: LoginFlowStep

        @MainActor var email: String
        @MainActor var password: String
        @MainActor var pin: String

        @MainActor var profiles: [(id: String, name: String, pinRequired: Bool)]
        @MainActor var selectedProfileId: String?
        @MainActor var selectedProfileRequiresPin: Bool

        @MainActor var loginError: LoginError?

        @MainActor
        init() {
            sheetPresented = false
            flowStep = .credentials

            email = TwentyFourSixClient.shared._email ?? ""
            password = ""
            pin = ""

            profiles = []
            selectedProfileId = nil
            selectedProfileRequiresPin = false

            loginError = nil
        }
    }
}

extension LoginView.LoginViewModel {
    func proceed() {
        Task {
            if await flowStep == .credentials {
                await MainActor.run {
                    flowStep = .credentialsLoading
                }

                // Step 1: Fetch profiles
                do {
                    let fetchedProfiles = try await TwentyFourSixClient.shared.fetchProfiles(
                        email: await email,
                        password: await password)

                    await MainActor.run {
                        profiles = fetchedProfiles

                        if fetchedProfiles.count == 1 {
                            // Auto-select single profile
                            selectedProfileId = fetchedProfiles[0].id
                            selectedProfileRequiresPin = fetchedProfiles[0].pinRequired
                        }

                        if fetchedProfiles.count > 1 {
                            // Show profile selection
                            loginError = nil
                            flowStep = .profileSelection
                        } else if fetchedProfiles.count == 1 && fetchedProfiles[0].pinRequired {
                            // Single profile that needs PIN
                            loginError = nil
                            flowStep = .pinEntry
                        } else {
                            // Single profile, no PIN needed - login directly
                            loginError = nil
                            flowStep = .credentialsLoading
                        }
                    }

                    // If we auto-selected and no pin needed, login now
                    if await flowStep == .credentialsLoading {
                        await performLogin()
                    }
                } catch {
                    await MainActor.run {
                        loginError = .failed
                        flowStep = .credentials
                    }
                }
            } else if await flowStep == .profileSelection {
                // Profile was selected, check if PIN is needed
                await MainActor.run {
                    if selectedProfileRequiresPin {
                        flowStep = .pinEntry
                    } else {
                        flowStep = .credentialsLoading
                    }
                }

                if await flowStep == .credentialsLoading {
                    await performLogin()
                }
            } else if await flowStep == .pinEntry {
                await MainActor.run {
                    flowStep = .credentialsLoading
                }
                await performLogin()
            }
        }
    }

    private func performLogin() async {
        do {
            let currentEmail = await email
            let currentPassword = await password
            let currentPin = await pin
            guard let profileId = await selectedProfileId else {
                await MainActor.run {
                    loginError = .failed
                    flowStep = .credentials
                }
                return
            }

            let token = try await TwentyFourSixClient.shared.login(
                email: currentEmail,
                password: currentPassword,
                profileId: profileId,
                pin: currentPin.isEmpty ? nil : currentPin)

            // Store credentials for re-auth
            TwentyFourSixClient.shared.store(token: token)
            TwentyFourSixClient.shared.store(email: currentEmail)
            TwentyFourSixClient.shared.store(password: currentPassword)
            TwentyFourSixClient.shared.store(profileId: profileId)
            if !currentPin.isEmpty {
                TwentyFourSixClient.shared.store(profilePin: currentPin)
            }

            // Register device
            try? await TwentyFourSixClient.shared.registerDevice()
        } catch {
            await MainActor.run {
                loginError = .failed
                flowStep = .credentials
            }
        }
    }

    @MainActor
    func selectProfile(id: String) {
        selectedProfileId = id
        selectedProfileRequiresPin = profiles.first(where: { $0.id == id })?.pinRequired ?? false
    }

    enum LoginFlowStep {
        case credentials
        case credentialsLoading
        case profileSelection
        case pinEntry
    }
    enum LoginError {
        case failed
    }
}
