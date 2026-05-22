// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { describe, it, expect } from 'vitest';
import { isValidEnvVarName, isValidContainerImage, isValidImageTag } from './validation';

describe('isValidEnvVarName', () => {
  it('accepts names starting with a letter', () => {
    expect(isValidEnvVarName('MY_VAR')).toBe(true);
    expect(isValidEnvVarName('a')).toBe(true);
    expect(isValidEnvVarName('Z')).toBe(true);
  });

  it('accepts names starting with an underscore', () => {
    expect(isValidEnvVarName('_MY_VAR')).toBe(true);
    expect(isValidEnvVarName('_')).toBe(true);
    expect(isValidEnvVarName('__')).toBe(true);
  });

  it('accepts names with letters, digits, and underscores', () => {
    expect(isValidEnvVarName('VAR_123')).toBe(true);
    expect(isValidEnvVarName('a1b2c3')).toBe(true);
    expect(isValidEnvVarName('_0')).toBe(true);
  });

  it('rejects empty string', () => {
    expect(isValidEnvVarName('')).toBe(false);
  });

  it('rejects names starting with a digit', () => {
    expect(isValidEnvVarName('1VAR')).toBe(false);
    expect(isValidEnvVarName('0_FOO')).toBe(false);
  });

  it('rejects names containing invalid characters', () => {
    expect(isValidEnvVarName('MY-VAR')).toBe(false);
    expect(isValidEnvVarName('MY.VAR')).toBe(false);
    expect(isValidEnvVarName('MY VAR')).toBe(false);
    expect(isValidEnvVarName('MY@VAR')).toBe(false);
    expect(isValidEnvVarName('path/to')).toBe(false);
  });

  it('rejects names with leading or trailing spaces', () => {
    expect(isValidEnvVarName(' MY_VAR')).toBe(false);
    expect(isValidEnvVarName('MY_VAR ')).toBe(false);
  });
});

describe('isValidContainerImage', () => {
  it('accepts NAMESPACE/REPOSITORY', () => {
    expect(isValidContainerImage('myorg/my-agent')).toBe(true);
    expect(isValidContainerImage('namespace/repo')).toBe(true);
  });

  it('accepts HOST/NAMESPACE/REPOSITORY', () => {
    expect(isValidContainerImage('quay.io/myorg/my-agent')).toBe(true);
    expect(isValidContainerImage('ghcr.io/owner/repo')).toBe(true);
    expect(isValidContainerImage('docker.io/library/nginx')).toBe(true);
  });

  it('accepts HOST:PORT/NAMESPACE/REPOSITORY', () => {
    expect(isValidContainerImage('localhost:5000/myns/myrepo')).toBe(true);
    expect(isValidContainerImage('registry.example.com:443/org/app')).toBe(true);
  });

  it('accepts segments with dots, underscores, and hyphens', () => {
    expect(isValidContainerImage('my.org/my_repo')).toBe(true);
    expect(isValidContainerImage('registry.io/my-ns/my.repo')).toBe(true);
  });

  it('rejects bare repository name without namespace', () => {
    expect(isValidContainerImage('my-agent')).toBe(false);
    expect(isValidContainerImage('nginx')).toBe(false);
  });

  it('rejects empty string', () => {
    expect(isValidContainerImage('')).toBe(false);
  });

  it('accepts deeper paths', () => {
    expect(isValidContainerImage('ghcr.io/kagenti/agent-examples/a2a_currency_converter')).toBe(true);
    expect(isValidContainerImage('registry.example.com:5000/org/repo/sub/path')).toBe(true);
    expect(isValidContainerImage('a/b/c/d')).toBe(true);
  });

  it('rejects empty segments', () => {
    expect(isValidContainerImage('/repo')).toBe(false);
    expect(isValidContainerImage('ns/')).toBe(false);
    expect(isValidContainerImage('host//repo')).toBe(false);
  });

  it('rejects segments starting or ending with special characters', () => {
    expect(isValidContainerImage('-ns/repo')).toBe(false);
    expect(isValidContainerImage('ns/repo-')).toBe(false);
    expect(isValidContainerImage('.ns/repo')).toBe(false);
    expect(isValidContainerImage('ns/.repo')).toBe(false);
  });

  it('rejects invalid host:port format', () => {
    expect(isValidContainerImage(':5000/ns/repo')).toBe(false);
    expect(isValidContainerImage('host:/ns/repo')).toBe(false);
    expect(isValidContainerImage('host:abc/ns/repo')).toBe(false);
  });

  it('rejects images with tags or digests embedded', () => {
    expect(isValidContainerImage('ns/repo:latest')).toBe(false);
    expect(isValidContainerImage('ns/repo@sha256:abc')).toBe(false);
  });
});

describe('isValidImageTag', () => {
  it('accepts typical tags', () => {
    expect(isValidImageTag('latest')).toBe(true);
    expect(isValidImageTag('v1.0.0')).toBe(true);
    expect(isValidImageTag('v2.3.1-rc1')).toBe(true);
  });

  it('accepts tags starting with a letter', () => {
    expect(isValidImageTag('release')).toBe(true);
    expect(isValidImageTag('A')).toBe(true);
  });

  it('accepts tags starting with a digit', () => {
    expect(isValidImageTag('1.0')).toBe(true);
    expect(isValidImageTag('0')).toBe(true);
  });

  it('accepts tags starting with an underscore', () => {
    expect(isValidImageTag('_build123')).toBe(true);
  });

  it('accepts tags with underscores, periods, and dashes', () => {
    expect(isValidImageTag('my_tag')).toBe(true);
    expect(isValidImageTag('my.tag')).toBe(true);
    expect(isValidImageTag('my-tag')).toBe(true);
    expect(isValidImageTag('a1.2_3-beta')).toBe(true);
  });

  it('rejects empty string', () => {
    expect(isValidImageTag('')).toBe(false);
  });

  it('rejects tags starting with a period', () => {
    expect(isValidImageTag('.hidden')).toBe(false);
    expect(isValidImageTag('.1')).toBe(false);
  });

  it('rejects tags starting with a dash', () => {
    expect(isValidImageTag('-flag')).toBe(false);
    expect(isValidImageTag('-1')).toBe(false);
  });

  it('rejects tags with spaces', () => {
    expect(isValidImageTag('my tag')).toBe(false);
    expect(isValidImageTag(' latest')).toBe(false);
  });

  it('rejects tags with non-ASCII or special characters', () => {
    expect(isValidImageTag('tag@1')).toBe(false);
    expect(isValidImageTag('tag:1')).toBe(false);
    expect(isValidImageTag('tag/1')).toBe(false);
    expect(isValidImageTag('tag!')).toBe(false);
    expect(isValidImageTag('tàg')).toBe(false);
  });
});
