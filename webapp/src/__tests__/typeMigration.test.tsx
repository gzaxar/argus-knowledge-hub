import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Resolution, statusBadge } from "../pages/admin/typeMigration/TypeMigrations";
import { renderWith } from "../test/render";

const base = { package_id: "it", type: "Server", checksum: "abc", installed_version: "1.1.0" };

describe("the migration wizard's target step", () => {
  it("says, per owning workspace, where the package type lives — the shared catalogue included", () => {
    renderWith(<Resolution rows={[
      { ...base, workspace_id: "line-a", home: "catalogue", schema_uid: "catalogue:argus-object:server", status: "ok", detail: null },
    ]} />);
    const row = screen.getByRole("row", { name: /line-a/ });
    expect(within(row).getByText(/shared catalogue/)).toBeInTheDocument();
    expect(within(row).getByText(/available/)).toBeInTheDocument();
  });

  it("names what is missing and offers the install preview and the packages page of the right workspace", () => {
    renderWith(<Resolution rows={[
      { ...base, workspace_id: "line-b", home: "catalogue", schema_uid: null, installed_version: null,
        status: "package_missing", detail: "it is not installed in 'catalogue' (the shared catalogue)" },
    ]} />);
    expect(screen.getByText(/not installed in 'catalogue'/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview the install" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open catalogue's packages/ })).toHaveAttribute("href", "/workspaces/catalogue/packages");
  });

  it("shows a plan's status in words", () => {
    renderWith(<>{statusBadge("partially_applied")}</>);
    expect(screen.getByText("partially applied")).toBeInTheDocument();
  });
});

describe("bringing a shared type home", () => {
  it("says which workspace gets its own copy, made when applied", () => {
    renderWith(<Resolution rows={[
      { ...base, workspace_id: "btf", home: "btf", schema_uid: null, status: "will_create",
        detail: "'btf' gets its own 'Server', a copy of 'catalogue''s (it 1.1.0)", copy_of: "catalogue:argus-object:server" },
    ]} />);
    expect(screen.getByText(/'btf' gets its own 'Server'/)).toBeInTheDocument();
    expect(screen.getByText(/made when applied/)).toBeInTheDocument();
  });
});
