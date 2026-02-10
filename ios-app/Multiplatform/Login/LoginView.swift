//
//  LoginView.swift
//  AmpFin
//
//  Login view for 24six authentication.
//

import SwiftUI
import AmpFinKit

struct LoginView: View {
    @State private var viewModel = LoginViewModel()

    var body: some View {
        WelcomeView(loginSheetPresented: $viewModel.sheetPresented)
            .sheet(isPresented: $viewModel.sheetPresented, content: {
                NavigationStack {
                    switch viewModel.flowStep {
                    case .credentials:
                        LoginFormView()
                    case .credentialsLoading:
                        LoadingView()
                    case .profileSelection:
                        ProfileSelectionView()
                    case .pinEntry:
                        PinEntryView()
                    }
                }
            })
            .transition(.opacity)
            .animation(.smooth, value: viewModel.flowStep)
            .environment(viewModel)
    }
}

// MARK: - Profile Selection View

struct ProfileSelectionView: View {
    @Environment(LoginView.LoginViewModel.self) private var viewModel

    var body: some View {
        VStack(spacing: 20) {
            Text("Select Profile")
                .font(.title2)
                .bold()

            ForEach(viewModel.profiles, id: \.id) { profile in
                Button(action: {
                    viewModel.selectProfile(id: profile.id)
                    viewModel.proceed()
                }) {
                    HStack {
                        Text(profile.name)
                            .font(.headline)
                        Spacer()
                        if profile.pinRequired {
                            Image(systemName: "lock.fill")
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding()
                    .background(.regularMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
            }
        }
        .padding()
        .navigationTitle("Choose Profile")
    }
}

// MARK: - PIN Entry View

struct PinEntryView: View {
    @Environment(LoginView.LoginViewModel.self) private var viewModel

    var body: some View {
        @Bindable var vm = viewModel

        VStack(spacing: 20) {
            Text("Enter PIN")
                .font(.title2)
                .bold()

            Text("This profile requires a PIN to access.")
                .foregroundStyle(.secondary)

            SecureField("PIN", text: $vm.pin)
                .textContentType(.oneTimeCode)
                .keyboardType(.numberPad)
                .textFieldStyle(.roundedBorder)
                .padding(.horizontal)

            Button("Continue") {
                viewModel.proceed()
            }
            .buttonStyle(.borderedProminent)
            .disabled(vm.pin.isEmpty)

            if viewModel.loginError != nil {
                Text("Login failed. Please check your PIN.")
                    .foregroundStyle(.red)
            }
        }
        .padding()
        .navigationTitle("PIN Required")
    }
}

#Preview {
    LoginView()
}
