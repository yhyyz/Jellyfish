import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

// 验证 React Testing Library + jest-dom matchers 工作
describe('RTL + jest-dom sanity', () => {
  it('renders a div with text', () => {
    render(<div>hello vitest</div>);
    expect(screen.getByText('hello vitest')).toBeInTheDocument();
  });
});
