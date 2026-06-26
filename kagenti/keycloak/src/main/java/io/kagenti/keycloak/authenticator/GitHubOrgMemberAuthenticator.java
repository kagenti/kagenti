package io.kagenti.keycloak.authenticator;

import jakarta.ws.rs.core.Response;
import org.jboss.logging.Logger;
import org.keycloak.authentication.AuthenticationFlowContext;
import org.keycloak.authentication.AuthenticationFlowError;
import org.keycloak.authentication.Authenticator;
import org.keycloak.authentication.authenticators.broker.AbstractIdpAuthenticator;
import org.keycloak.authentication.authenticators.broker.util.SerializedBrokeredIdentityContext;
import org.keycloak.broker.provider.BrokeredIdentityContext;
import org.keycloak.models.AuthenticatorConfigModel;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.UserModel;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

/**
 * Keycloak First Broker Login authenticator that rejects logins from users
 * who are not public members of a configured GitHub organization.
 *
 * Reads the GitHub login from the brokered identity context (the IdP attaches
 * it to the auth session) and calls GitHub's anonymous public-membership
 * endpoint:
 *
 *   GET https://api.github.com/orgs/{org}/members/{username}
 *     204 -> public member (allow)
 *     404 -> not a public member (deny)
 *     302 -> requester not a member (n/a anonymous, treated as deny)
 *
 * Configure the required org via the authenticator config in the flow editor
 * (key: "org"). Defaults to "kagenti" if unset.
 */
public class GitHubOrgMemberAuthenticator implements Authenticator {

    private static final Logger LOG = Logger.getLogger(GitHubOrgMemberAuthenticator.class);

    static final String CONFIG_ORG = "org";
    static final String DEFAULT_ORG = "kagenti";
    private static final int CONNECT_TIMEOUT_MS = 5000;
    private static final int READ_TIMEOUT_MS = 5000;

    @Override
    public void authenticate(AuthenticationFlowContext context) {
        String org = configuredOrg(context);

        SerializedBrokeredIdentityContext serialized =
                SerializedBrokeredIdentityContext.readFromAuthenticationSession(
                        context.getAuthenticationSession(),
                        AbstractIdpAuthenticator.BROKERED_CONTEXT_NOTE);

        if (serialized == null) {
            LOG.warn("No brokered identity context on auth session; this authenticator must run inside a First Broker Login flow.");
            deny(context, "Brokered identity not available");
            return;
        }

        BrokeredIdentityContext brokered =
                serialized.deserialize(context.getSession(), context.getAuthenticationSession());

        String login = brokered.getUsername();
        if (login == null || login.isBlank()) {
            LOG.warn("Brokered identity has no username; cannot check org membership.");
            deny(context, "GitHub login missing from brokered identity");
            return;
        }

        if (isPublicMember(org, login)) {
            LOG.debugf("User '%s' is a public member of '%s'; allowing.", login, org);
            context.success();
        } else {
            LOG.infof("User '%s' is not a public member of '%s'; denying.", login, org);
            deny(context, "Not a public member of " + org);
        }
    }

    private String configuredOrg(AuthenticationFlowContext context) {
        AuthenticatorConfigModel cfg = context.getAuthenticatorConfig();
        if (cfg == null || cfg.getConfig() == null) {
            return DEFAULT_ORG;
        }
        String v = cfg.getConfig().get(CONFIG_ORG);
        return (v == null || v.isBlank()) ? DEFAULT_ORG : v.trim();
    }

    private boolean isPublicMember(String org, String username) {
        HttpURLConnection conn = null;
        try {
            LOG.infof("Checking GitHub API for org=%s user=%s", org, username);
            String url = "https://api.github.com/orgs/"
                    + URLEncoder.encode(org, StandardCharsets.UTF_8)
                    + "/members/"
                    + URLEncoder.encode(username, StandardCharsets.UTF_8);
            conn = (HttpURLConnection) URI.create(url).toURL().openConnection();
            conn.setRequestMethod("GET");
            conn.setRequestProperty("Accept", "application/vnd.github+json");
            conn.setRequestProperty("User-Agent", "keycloak-github-org-authenticator");
            // With this some requests give 302
            // conn.setInstanceFollowRedirects(false);
            conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
            conn.setReadTimeout(READ_TIMEOUT_MS);

            int code = conn.getResponseCode();
            LOG.infof("GitHub API for org=%s user=%s code=%d", org, username, code);
            return code == HttpURLConnection.HTTP_NO_CONTENT;
        } catch (IOException e) {
            LOG.warnf(e, "Error calling GitHub API for org=%s user=%s; failing closed.", org, username);
            return false;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private void deny(AuthenticationFlowContext context, String message) {
        Response response = Response.status(Response.Status.FORBIDDEN)
                .entity(message)
                .build();
        context.failure(AuthenticationFlowError.ACCESS_DENIED, response);
    }

    @Override
    public void action(AuthenticationFlowContext context) {
        // No interactive step.
    }

    @Override
    public boolean requiresUser() {
        return false;
    }

    @Override
    public boolean configuredFor(KeycloakSession session, RealmModel realm, UserModel user) {
        return true;
    }

    @Override
    public void setRequiredActions(KeycloakSession session, RealmModel realm, UserModel user) {
        // No required actions.
    }

    @Override
    public void close() {
        // No resources to release.
    }
}
