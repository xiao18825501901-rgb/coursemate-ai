import { describe, expect, it } from 'vitest';
import { developmentServiceNotice, serviceConnectionLabel } from './servicePresentation.js';

const FORBIDDEN_SYSTEM_TERMS = /deepseek|qwen|千问|provider|模型型号/i;

describe('system service presentation', () => {
  it.each(['disabled', 'test', 'qwen', 'future-provider'])(
    'uses a provider-neutral connection label for %s',
    providerMode => {
      expect(serviceConnectionLabel(providerMode)).not.toMatch(FORBIDDEN_SYSTEM_TERMS);
    },
  );

  it.each(['disabled', 'test', 'qwen', 'future-provider'])(
    'uses a provider-neutral development notice for %s',
    providerMode => {
      expect(developmentServiceNotice(providerMode)).not.toMatch(FORBIDDEN_SYSTEM_TERMS);
    },
  );
});
