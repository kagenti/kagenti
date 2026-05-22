// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

export type KeycloakRedirectLocation = Pick<Location, 'origin' | 'pathname'>;

/**
 * OAuth redirect_uri for Keycloak. The UI client registers root_url/*.
 * Backend config often supplies only the app root; using that for every page
 * makes check-sso (with iframe disabled) and login return to home. Use the
 * current URL path so refresh and deep links preserve the route.
 *
 * @param loc - optional override for tests; defaults to window.location
 */
export function keycloakRedirectUri(
  configuredRedirect: string | undefined,
  loc?: KeycloakRedirectLocation
): string {
  const origin =
    loc?.origin ??
    (typeof window !== 'undefined' ? window.location.origin : '');
  const pathname =
    loc?.pathname ??
    (typeof window !== 'undefined' ? window.location.pathname : '/');

  const path = !pathname || pathname === '' ? '/' : pathname;
  const atCurrentPath = `${origin}${path}`;

  if (!configuredRedirect?.trim()) {
    return atCurrentPath || '/';
  }

  try {
    const parsed = new URL(configuredRedirect);
    const basePath = (parsed.pathname || '/').replace(/\/$/, '') || '/';
    if (basePath === '/' || basePath === '') {
      return atCurrentPath;
    }
    return configuredRedirect;
  } catch {
    return configuredRedirect;
  }
}
