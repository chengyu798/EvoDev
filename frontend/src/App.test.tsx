import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

describe("App", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the product promise", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ status: "ok", version: "0.1.0", docker_available: true }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<App />);

    expect(screen.getByText(/Turn an issue into/i)).toBeInTheDocument();
    expect(await screen.findByText("API v0.1.0")).toBeInTheDocument();
  });
});
