// 引入 RTL 的 jest-dom matchers，使 expect(el).toBeInTheDocument() 等可用
import '@testing-library/jest-dom/vitest';

// 清理每个测试后的 DOM，避免上下游污染
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});

// jsdom 没有实现 window.matchMedia，antd v5 的 Grid / Modal / Tooltip 等
// 组件初始化阶段会调用，必须用最简空实现兜底，否则触发
// `TypeError: window.matchMedia is not a function`。
if (typeof window !== 'undefined' && !window.matchMedia) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  });
}

