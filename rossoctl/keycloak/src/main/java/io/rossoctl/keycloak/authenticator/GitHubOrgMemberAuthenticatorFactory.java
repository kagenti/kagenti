package io.rossoctl.keycloak.authenticator;

import org.keycloak.Config;
import org.keycloak.authentication.Authenticator;
import org.keycloak.authentication.AuthenticatorFactory;
import org.keycloak.models.AuthenticationExecutionModel;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.provider.ProviderConfigProperty;

import java.util.List;

public class GitHubOrgMemberAuthenticatorFactory implements AuthenticatorFactory {

    public static final String PROVIDER_ID = "github-org-member-authenticator";

    private static final GitHubOrgMemberAuthenticator SINGLETON = new GitHubOrgMemberAuthenticator();

    private static final AuthenticationExecutionModel.Requirement[] REQUIREMENT_CHOICES = {
            AuthenticationExecutionModel.Requirement.REQUIRED,
            AuthenticationExecutionModel.Requirement.DISABLED
    };

    @Override
    public String getId() {
        return PROVIDER_ID;
    }

    @Override
    public String getDisplayType() {
        return "GitHub Org Member Check";
    }

    @Override
    public String getReferenceCategory() {
        return "github-org";
    }

    @Override
    public boolean isConfigurable() {
        return true;
    }

    @Override
    public AuthenticationExecutionModel.Requirement[] getRequirementChoices() {
        return REQUIREMENT_CHOICES;
    }

    @Override
    public boolean isUserSetupAllowed() {
        return false;
    }

    @Override
    public String getHelpText() {
        return "Rejects First Broker Login from the GitHub IdP if the user is not a public member of the configured GitHub organization.";
    }

    @Override
    public List<ProviderConfigProperty> getConfigProperties() {
        ProviderConfigProperty org = new ProviderConfigProperty();
        org.setName(GitHubOrgMemberAuthenticator.CONFIG_ORG);
        org.setLabel("GitHub organization");
        org.setType(ProviderConfigProperty.STRING_TYPE);
        org.setHelpText("The GitHub organization whose public members are allowed to log in. Example: rossoctl");
        org.setDefaultValue(GitHubOrgMemberAuthenticator.DEFAULT_ORG);
        return List.of(org);
    }

    @Override
    public Authenticator create(KeycloakSession session) {
        return SINGLETON;
    }

    @Override
    public void init(Config.Scope config) {
        // Nothing to initialize.
    }

    @Override
    public void postInit(KeycloakSessionFactory factory) {
        // Nothing to post-initialize.
    }

    @Override
    public void close() {
        // Nothing to close.
    }
}
