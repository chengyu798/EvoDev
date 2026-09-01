// 验证首页中文文案和服务状态能够正确显示。
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

describe("首页", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("显示产品定位和服务状态", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ status: "ok", version: "0.1.0", docker_available: true }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<App />);

    expect(screen.getByText(/将问题转化为/)).toBeInTheDocument();
    expect(await screen.findByText("后端服务已连接")).toBeInTheDocument();
  });
});
