import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrollIntoView
Element.prototype.scrollIntoView = vi.fn();

beforeEach(() => {
  window.sessionStorage.clear();
});
