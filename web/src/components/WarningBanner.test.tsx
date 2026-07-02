import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WarningBanner } from "./WarningBanner";

describe("WarningBanner", () => {
  it("renders nothing when there are no warnings", () => {
    const { container } = render(<WarningBanner warnings={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists every warning it's given", () => {
    render(<WarningBanner warnings={["look-ahead bias possible", "high turnover"]} />);
    expect(screen.getByText("look-ahead bias possible")).toBeInTheDocument();
    expect(screen.getByText("high turnover")).toBeInTheDocument();
  });
});
