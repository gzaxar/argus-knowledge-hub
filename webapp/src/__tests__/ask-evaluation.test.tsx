import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { askEvalApi, type AskEvalRun } from "../api/client";
import { AskEvaluationPage } from "../pages/admin/AskEvaluation";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const run: AskEvalRun = {
  id: "r1", kind: "benchmark", release: "1.35.94", commit: "abc", status: "finished", source: "upload",
  requested_by: null, models: ["m-a", "m-b"], progress: null, report_sha256: "f".repeat(64), public_sha256: null,
  error: null, created_at: "", started_at: null, finished_at: null,
  summary: [{ model: "m-a", runs: 24, pass_rate: 0.75, factual_pass_rate: 0.8, evidence_retrieval: 0.9,
              citation_support: 1, correct_abstention: 0.5, critical_failures: 1, completion_failures: 0,
              latency_p50_s: 4.2, latency_p95_s: 9.9, tokens_mean: 5100 },
            { model: "m-b", status: "unavailable", reason: "the server does not list this model" }],
  report: { cases: [{ id: "linac-moxa-4003-cables", language: "en", domain: "accelerator", severity: "critical",
                      role: "reader", question: "Which power supplies share Moxa port 4003?",
                      results: { "m-a": [{ attempt: 0, seconds: 3.1, answer: "PS-Q1, PS-Q2, PS-Q3; cables not recorded.",
                                           steps: [{ tool: "get_object", arguments: {}, result: "{}" }],
                                           scores: { passed: false, critical: [], reasons: ["required fact missing: x"] } }] } }] },
};

describe("Administration › Ask evaluation", () => {
  it("says not run for a release without a run, and drills down to a case's answer and reasons", async () => {
    vi.spyOn(askEvalApi, "settings").mockResolvedValue({ base_url: "https://ai.example/v1", api_key_set: true,
      models: ["m-a", "m-b"], release_model: "m-a", embedding_model: null, rerank_model: null, judge_model: null,
      judge_base_url: null, judge_api_key_set: false, approved_hosts: [], repeats: 3, case_timeout_s: 300,
      max_output_tokens: null, updated_by: null, updated_at: null, database_configured: false });
    vi.spyOn(askEvalApi, "releases").mockResolvedValue({ current: "1.35.95", releases: [
      { release: "1.35.95", current: true, runs: 0, release_quality: { status: "not run" }, benchmark: { status: "not run" } },
      { release: "1.35.94", current: false, runs: 1, release_quality: { status: "not run" }, benchmark: run }] });
    vi.spyOn(askEvalApi, "runs").mockResolvedValue([run]);
    vi.spyOn(askEvalApi, "run").mockResolvedValue(run);
    renderWith(<AskEvaluationPage />);

    await screen.findByText("1.35.95");
    // Both of this release's columns and 1.35.94's release-quality column (and the page's own sentence).
    expect(screen.getAllByText("not run")).toHaveLength(4);
    expect(screen.getByText(/No evaluation database is configured/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "finished" })[0]);
    await waitFor(() => expect(screen.getByText("75%")).toBeInTheDocument());
    expect(screen.getByText(/the server does not list this model/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("linac-moxa-4003-cables"));
    expect(screen.getByText("required fact missing: x")).toBeInTheDocument();
    expect(screen.getByText(/cables not recorded/)).toBeInTheDocument();
  });
});
