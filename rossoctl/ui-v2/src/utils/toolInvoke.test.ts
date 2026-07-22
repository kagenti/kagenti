// Copyright 2026 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { describe, it, expect } from 'vitest';
import { initialInvokeArgs, buildInvokeArgs } from './toolInvoke';

describe('initialInvokeArgs', () => {
  it('returns empty object when no properties', () => {
    expect(initialInvokeArgs(undefined)).toEqual({});
    expect(initialInvokeArgs({})).toEqual({});
  });

  it('does not fabricate sentinels for typed properties', () => {
    const props = {
      city: { default: undefined },
      party_size: {},
      cuisine: {},
    };
    expect(initialInvokeArgs(props)).toEqual({});
  });

  it('honors explicit defaults only', () => {
    const props = { limit: { default: 10 }, name: {} };
    expect(initialInvokeArgs(props)).toEqual({ limit: 10 });
  });
});

describe('buildInvokeArgs', () => {
  it('always keeps required keys even if empty', () => {
    const args = { city: '' };
    expect(buildInvokeArgs(args, ['city'])).toEqual({ city: '' });
  });

  it('drops unset optionals (undefined and empty string)', () => {
    const args = { city: 'Boston', cuisine: '', party_size: undefined };
    expect(buildInvokeArgs(args, ['city'])).toEqual({ city: 'Boston' });
  });

  it('keeps optional values that are explicitly set, including 0 and false', () => {
    const args = { city: 'Boston', party_size: 0, promo: false, note: 'hi' };
    expect(buildInvokeArgs(args, ['city'])).toEqual({
      city: 'Boston',
      party_size: 0,
      promo: false,
      note: 'hi',
    });
  });
});
