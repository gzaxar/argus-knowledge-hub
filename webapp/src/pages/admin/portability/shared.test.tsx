import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { portabilityApi } from "../../../api/client";
import type { PortabilityJob } from "../../../api/portabilityTypes";
import { JobProgress, useJob } from "./shared";

vi.mock("../../../api/client", () => ({
  portabilityApi: { job: vi.fn(), jobs: vi.fn() }, problemText: String,
}));
const job: PortabilityJob = {
  id: "job-test", subject_kind: "export", subject_id: "exp-test", action: "analyse",
  state: "running", requested_by: "tester", created_at: "2026-11-19T10:00:00Z",
  started_at: "2026-11-19T10:00:00Z", finished_at: null, error: null, metrics: {},
};
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks(); });

describe("export progress", () => {
  it("shows an accessible animated bar without inventing a percentage", () => {
    render(<JobProgress job={job} />);
    expect(screen.getByText(/Analysing content for export/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  });
  it("shows reported stages, counts and measured percentages", () => {
    render(<JobProgress job={{ ...job, metrics: { progress: {
      stage: "Checking attachments", done: 3, total: 8, percent: 37.5, at: job.created_at!,
    } } }} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "37.5");
    expect(screen.getByText(/3 of 8/)).toBeInTheDocument();
    expect(screen.getByText("Checking attachments")).toBeInTheDocument();
  });
  it("keeps polling after a temporary failure and reloads on completion", async () => {
    vi.useFakeTimers();
    vi.mocked(portabilityApi.job).mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ ...job, state: "completed" });
    const done = vi.fn();
    const { result } = renderHook(() => useJob(done));
    act(() => result.current.setJob(job));
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(result.current.pollError).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(result.current.job?.state).toBe("completed");
    expect(result.current.pollError).toBe(false);
    expect(done).toHaveBeenCalledTimes(1);
    expect(portabilityApi.job).toHaveBeenCalledTimes(2);
  });
  it("reattaches after a refresh and retries failed job discovery", async () => {
    vi.useFakeTimers();
    vi.mocked(portabilityApi.jobs).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([job]);
    vi.mocked(portabilityApi.job).mockResolvedValue({ ...job, state: "completed" });
    const done = vi.fn();
    const { result } = renderHook(() => useJob(done, job.subject_id));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.pollError).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(result.current.job?.id).toBe(job.id);
    expect(result.current.running).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(result.current.running).toBe(false);
    expect(result.current.job?.state).toBe("completed");
  });
  it("ignores an in-flight response after the page unmounts", async () => {
    vi.useFakeTimers();
    let resolve!: (job: PortabilityJob) => void;
    vi.mocked(portabilityApi.job).mockImplementation(() => new Promise((r) => { resolve = r; }));
    const done = vi.fn();
    const { result, unmount } = renderHook(() => useJob(done));
    act(() => result.current.setJob(job));
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    unmount();
    await act(async () => { resolve({ ...job, state: "completed" }); });
    expect(done).not.toHaveBeenCalled();
  });
});
