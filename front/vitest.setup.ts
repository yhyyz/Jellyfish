// 引入 RTL 的 jest-dom matchers，使 expect(el).toBeInTheDocument() 等可用
import '@testing-library/jest-dom/vitest';

// 清理每个测试后的 DOM，避免上下游污染
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});
