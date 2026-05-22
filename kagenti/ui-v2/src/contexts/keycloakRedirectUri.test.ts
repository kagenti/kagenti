// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { describe, it, expect } from 'vitest';

import { keycloakRedirectUri } from './keycloakRedirectUri';

const loc = { origin: 'https://ui.example.com', pathname: '/agents' };

describe('keycloakRedirectUri', () => {
  it('uses current path when configured redirect is app root', () => {
    expect(keycloakRedirectUri('https://ui.example.com/', loc)).toBe(
      'https://ui.example.com/agents'
    );
  });

  it('uses current path for root without trailing slash', () => {
    expect(keycloakRedirectUri('https://ui.example.com', loc)).toBe(
      'https://ui.example.com/agents'
    );
  });

  it('returns configured URI when it is a non-root callback path', () => {
    const custom = 'https://ui.example.com/oauth/callback';
    expect(keycloakRedirectUri(custom, loc)).toBe(custom);
  });

  it('uses current path when no config', () => {
    expect(keycloakRedirectUri(undefined, loc)).toBe(
      'https://ui.example.com/agents'
    );
  });

  it('home path stays on home', () => {
    expect(
      keycloakRedirectUri('https://ui.example.com/', {
        origin: 'https://ui.example.com',
        pathname: '/',
      })
    ).toBe('https://ui.example.com/');
  });
});
