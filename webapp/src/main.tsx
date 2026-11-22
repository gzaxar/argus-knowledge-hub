import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { refusalToTell } from "./lib/queryErrors";
import { adoptWorkspaceFromUrl } from "./api/session";
import { ToastHost, showToast } from "./components/Toast";
import { DialogHost } from "./lib/dialogs";
import "./index.css";

function handleError(error: unknown, meta?: Record<string, unknown>) {
  if (refusalToTell(error, meta)) showToast("You don't have permission to do that.");
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 10_000 },
  },
  queryCache: new QueryCache({ onError: (error, query) => handleError(error, query.meta) }),
  mutationCache: new MutationCache({ onError: (error) => handleError(error) }),
});

adoptWorkspaceFromUrl();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
      <ToastHost />
      <DialogHost />
    </QueryClientProvider>
  </React.StrictMode>,
);
