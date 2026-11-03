import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { placesApi, type AssetLocationView } from "../api/client";
import { FullPage, useFullPage } from "../components/FullPage";
import { LocationCard } from "../components/LocationCard";
import { renderWith } from "../test/render";

vi.mock("react-leaflet", () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div data-testid="map">{children}</div>;
  const Nothing = () => null;
  return { MapContainer: Box, TileLayer: Nothing, CircleMarker: Nothing, Polygon: Nothing, Polyline: Nothing,
           GeoJSON: Nothing, Tooltip: Nothing, ImageOverlay: Nothing,
           useMap: () => ({ fitBounds: () => undefined, setView: () => undefined }), useMapEvents: () => null };
});

afterEach(() => vi.restoreAllMocks());

function Where() {
  return <span>{useFullPage() ? "full" : "inline"}</span>;
}

describe("a map operation in a full-page window (issue #13)", () => {
  it("is inline until opened, then over the whole page, and Escape closes it", () => {
    const close = vi.fn();
    const { rerender } = renderWith(<FullPage open={false} title="Place it" onClose={close}><Where /></FullPage>);
    expect(screen.getByText("inline")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    rerender(<FullPage open title="Place it" onClose={close}><Where /></FullPage>);
    expect(screen.getByRole("dialog", { name: "Place it" })).toHaveTextContent("full");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).toHaveBeenCalled();
  });

  it("opens setting a unit's position full page, and the page's map has a Full page button", async () => {
    vi.spyOn(placesApi, "location").mockResolvedValue({ uid: "u1", locatable: true, map_layer: null, hidden: false,
      location: null, route: null, outline: null, history: [], observations: [] } as AssetLocationView);
    renderWith(<LocationCard uid="u1" editable />);
    expect(await screen.findByRole("button", { name: "Full page" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Set its position" }));
    const dialog = await screen.findByRole("dialog", { name: "Set its position" });
    expect(dialog).toHaveTextContent("Click the map, or type WGS 84 coordinates.");
    expect(screen.queryByRole("button", { name: "Full page" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Close/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
