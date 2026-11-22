import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SHEET_DROP } from "../api/client";
import { ValueMatches } from "../pages/assets/SpreadsheetImport";

describe("matching a column's values to a choice list", () => {
  const column = {
    column: "Stato", target: "argus_lifecycle",
    values: { "In servizio": "In service", Scorta: "Standby" },
    value_sources: { "In servizio": "rule" as const, Scorta: "ai" as const },
  };

  it("shows each value with its choice and who proposed it, and counts what is still to match", () => {
    render(<ValueMatches column={column} choices={["In service", "Standby", "Faulty"]}
                         fileValues={["In servizio", "Scorta", "Boh"]} onChange={() => {}} />);
    expect(screen.getByRole("combobox", { name: "In servizio in Stato" })).toHaveValue("In service");
    expect(screen.getByRole("combobox", { name: "Boh in Stato" })).toHaveValue("");
    expect(screen.getByText("rule")).toBeInTheDocument();
    expect(screen.getByText("AI")).toBeInTheDocument();
    expect(screen.getByText(/1 to match/)).toBeInTheDocument();
  });

  it("lets the person choose a value's choice, or leave it out", () => {
    const onChange = vi.fn();
    render(<ValueMatches column={column} choices={["In service", "Standby", "Faulty"]}
                         fileValues={["In servizio", "Scorta", "Boh"]} onChange={onChange} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Boh in Stato" }), { target: { value: SHEET_DROP } });
    expect(onChange).toHaveBeenCalledWith("Boh", SHEET_DROP);
    fireEvent.change(screen.getByRole("combobox", { name: "Scorta in Stato" }), { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith("Scorta", null);
  });
});
