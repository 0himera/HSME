import type {
  DocInfo,
  Statistics,
  Gap,
  SearchResult,
  Counterfactual,
  EnrichedGap,
  UserSession,
  Entity,
  GraphData,
  Experiment,
  IngestStatus
} from "./types";

interface SearchResponse {
  total: number;
  results: SearchResult[];
  rag_explanation?: string;
}

const BACKEND_BASE = typeof window !== "undefined" && window.location.port === "3000"
  ? "http://localhost:8000"
  : "";

function getHeaders(user: UserSession): Record<string, string> {
  return {
    "Content-Type": "application/json",
    "X-User-Name": encodeURIComponent(user.name),
    "X-User-Role": user.role,
  };
}

export async function fetchDocuments(user: UserSession): Promise<{ data: DocInfo[]; live: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/documents`, {
      headers: getHeaders(user),
    });
    if (!res.ok) throw new Error("Failed to fetch documents");
    const data = await res.json();
    return { data, live: true };
  } catch (err) {
    console.error(err);
    return { data: [], live: false };
  }
}

export async function fetchExperiments(user: UserSession): Promise<{ data: Experiment[]; live: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/experiments`, {
      headers: getHeaders(user),
    });
    if (!res.ok) throw new Error("Failed to fetch experiments");
    const data = await res.json();
    return { data, live: true };
  } catch (err) {
    console.error(err);
    return { data: [], live: false };
  }
}


export async function fetchStatistics(user: UserSession): Promise<{ data: Statistics | null; live: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/statistics`, {
      headers: getHeaders(user),
    });
    if (!res.ok) throw new Error("Failed to fetch statistics");
    const data = await res.json();
    return { data, live: true };
  } catch (err) {
    console.error(err);
    return { data: null, live: false };
  }
}

export async function fetchGaps(user: UserSession, dimensions: string[]): Promise<{ data: Gap[]; live: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/gaps`, {
      method: "POST",
      headers: getHeaders(user),
      body: JSON.stringify({ dimensions }),
    });
    if (!res.ok) throw new Error("Failed to fetch gaps");
    const data = await res.json();
    return { data, live: true };
  } catch (err) {
    console.error(err);
    return { data: [], live: false };
  }
}

export async function searchQuery(
  user: UserSession,
  query: string,
  options: { geography: string | null }
): Promise<{ data: SearchResponse; live: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/search`, {
      method: "POST",
      headers: getHeaders(user),
      body: JSON.stringify({
        query,
        geography: options.geography || undefined,
        paged: true,
        limit: 10,
      }),
    });
    if (!res.ok) throw new Error("Failed to execute search query");
    const data = await res.json();
    return { data, live: true };
  } catch (err) {
    console.error(err);
    return {
      data: { total: 0, results: [] },
      live: false,
    };
  }
}

export async function fetchCounterfactuals(
  user: UserSession,
  experimentId: string
): Promise<{ data: Counterfactual[]; live: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/counterfactuals/${experimentId}`, {
      headers: getHeaders(user),
    });
    if (!res.ok) throw new Error("Failed to fetch counterfactuals");
    const data = await res.json();
    return { data, live: true };
  } catch (err) {
    console.error(err);
    return { data: [], live: false };
  }
}

export async function enrichGap(
  user: UserSession,
  gapConfig: Entity[]
): Promise<{ data: EnrichedGap | undefined; live: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/enrich-gap`, {
      method: "POST",
      headers: getHeaders(user),
      body: JSON.stringify(gapConfig),
    });
    if (!res.ok) throw new Error("Failed to enrich gap");
    const data = await res.json();
    return { data, live: true };
  } catch (err) {
    console.error(err);
    return { data: undefined, live: false };
  }
}

export async function fetchGraph(user: UserSession): Promise<{ data: GraphData | null; live: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/graph`, {
      headers: getHeaders(user),
    });
    if (!res.ok) throw new Error("Failed to fetch graph data");
    const data = await res.json();
    return { data, live: true };
  } catch (err) {
    console.error(err);
    return { data: null, live: false };
  }
}

export async function fetchIngestStatus(user: UserSession): Promise<{ data: IngestStatus | null; live: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/ingest-status`, {
      headers: getHeaders(user),
    });
    if (!res.ok) throw new Error("Failed to fetch ingest status");
    const data = await res.json();
    return { data, live: true };
  } catch (err) {
    console.error(err);
    return { data: null, live: false };
  }
}

export async function startIngestCorpus(user: UserSession): Promise<{ status: string; message: string }> {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/ingest-corpus`, {
      method: "POST",
      headers: getHeaders(user),
    });
    return await res.json();
  } catch (err: any) {
    console.error(err);
    return { status: "failed", message: err.message || "Failed to start corpus ingestion" };
  }
}




