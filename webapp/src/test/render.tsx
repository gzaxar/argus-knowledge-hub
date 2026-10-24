import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

/** A component inside a router and a query cache filled with what it would have fetched. */
export function renderWith(ui: React.ReactNode, { path = "/", cache = {} as Record<string, unknown> } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  for (const [key, value] of Object.entries(cache)) client.setQueryData(JSON.parse(key), value);
  let location = "";
  function Where() {
    const l = useLocation();
    location = l.pathname + l.search;
    return null;
  }
  const utils = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="*" element={<>{ui}<Where /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...utils, client, location: () => location };
}
