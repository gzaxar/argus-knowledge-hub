import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { ApiError } from "./api/client";
import { adoptWorkspaceFromUrl } from "./api/session";
import { ToastHost, showToast } from "./components/Toast";
import "./index.css";

function handleError(error: unknown) {
  if (error instanceof ApiError && error.status === 403) {
    showToast("You don't have permission to do that.");
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 10_000 },
  },
  queryCache: new QueryCache({ onError: handleError }),
  mutationCache: new MutationCache({ onError: handleError }),
});

adoptWorkspaceFromUrl();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
      <ToastHost />
    </QueryClientProvider>
  </React.StrictMode>,
);
