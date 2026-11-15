import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { indoorApi } from "../api/client";
import { PlanDrawer, freeSpot } from "../components/PlanDrawer";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const rooms = [{ uid: "rm-1", key: "B-RACKS", name: "Rack room", type: "Room" }];

describe("drawing a plan when there is no drawing", () => {
  it("adds rooms, one standing for a room record, sizes them exactly and creates the plan", async () => {
    const preview = vi.spyOn(indoorApi, "drawingPreview").mockResolvedValue("blob:plan");
    const draw = vi.spyOn(indoorApi, "drawPlan").mockResolvedValue({ uid: "pl", rooms_placed: 1 } as never);
    const done = vi.fn();
    renderWith(<PlanDrawer placeUid="hall" placeName="Hall B" levels={[]} roomsHere={rooms} onDone={done} />);

    expect(screen.getByLabelText("Title")).toHaveValue("Hall B — plan");
    fireEvent.click(screen.getByRole("button", { name: "+ Rack room" }));                 // from the record
    expect(screen.getByLabelText("Room name")).toHaveValue("Rack room");
    expect(screen.getByLabelText("The room record it stands for")).toHaveValue("rm-1");
    expect(screen.queryByRole("button", { name: "+ Rack room" })).toBeNull();             // used once
    fireEvent.click(screen.getByRole("button", { name: "+ a room" }));                     // a free one, next to it
    fireEvent.change(screen.getByLabelText("Room name"), { target: { value: "Control room" } });
    fireEvent.change(screen.getByLabelText("Room number"), { target: { value: "B0.02" } });
    fireEvent.change(screen.getByLabelText("Room w"), { target: { value: "10" } });
    await waitFor(() => expect(preview).toHaveBeenCalled());
    expect(await screen.findByAltText("The plan as it will be drawn")).toHaveAttribute("src", "blob:plan");

    fireEvent.click(screen.getByRole("button", { name: "Create the plan" }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    const body = draw.mock.calls[0][1];
    expect(draw.mock.calls[0][0]).toBe("hall");
    expect(body.place_rooms).toBe(true);
    expect(body.layout.rooms).toEqual([
      { name: "Rack room", number: "", record: "rm-1", w: 6, d: 5, x: 0, y: 0 },
      { name: "Control room", number: "B0.02", w: 10, d: 5, x: 6, y: 0 },
    ]);
  });

  it("says an uploaded drawing cannot be changed here", async () => {
    vi.spyOn(indoorApi, "drawingPreview").mockResolvedValue("blob:plan");
    vi.spyOn(indoorApi, "planLayout").mockResolvedValue({ editable: false, layout: null });
    renderWith(<PlanDrawer placeUid="hall" levels={[]} planUid="pl-up" roomsHere={[]} onDone={() => {}} />);
    expect(await screen.findByText(/uploaded drawing, not one drawn in ARGUS/)).toBeInTheDocument();
  });

  it("finds the first free spot for a room, or none", () => {
    const layout = { title: "t", width_m: 12, depth_m: 5, rooms: [{ name: "A", x: 0, y: 0, w: 6, d: 5 }] };
    expect(freeSpot(layout, 6, 5)).toEqual({ x: 6, y: 0 });
    expect(freeSpot({ ...layout, rooms: [...layout.rooms, { name: "B", x: 6, y: 0, w: 6, d: 5 }] }, 2, 2)).toBeNull();
  });
});
