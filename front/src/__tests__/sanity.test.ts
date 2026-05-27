import { describe, it, expect } from 'vitest';

// 简单的 sanity 检查，验证 vitest 工具链生效
describe('vitest sanity', () => {
  it('runs basic assertion', () => {
    expect(1).toBe(1);
  });

  it('runs async assertion', async () => {
    const result = await Promise.resolve('hello');
    expect(result).toBe('hello');
  });
});
