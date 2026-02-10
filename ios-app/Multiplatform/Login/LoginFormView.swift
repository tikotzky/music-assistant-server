//
//  LoginFormView.swift
//  AmpFin
//
//  Created by Rasmus Krämer on 16.11.24.
//

import SwiftUI

extension LoginView {
    struct LoginFormView: View {
        @Environment(LoginViewModel.self) private var viewModel
        
        var body: some View {
            @Bindable var viewModel = viewModel
            
            Form {
                Section {
                    TextField("login.email", text: $viewModel.email)
                        .keyboardType(.emailAddress)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)

                    SecureField("login.password", text: $viewModel.password)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)

                    Button {
                        viewModel.proceed()
                    } label: {
                        Text("login.next")
                    }
                } header: {
                    Text("login.title")
                } footer: {
                    Group {
                        switch viewModel.loginError {
                            case .failed:
                                Text("login.error.failed")
                            case nil:
                                EmptyView()
                        }
                    }
                    .foregroundStyle(.red)
                }
            }
            .onSubmit(viewModel.proceed)
        }
    }
}
