export interface UserSession {
  name: string;
  role: string;
}

export interface Statistics {
  total_experiments: number;
  entity_counts: Record<string, number>;
  distinct_counts: Record<string, number>;
}

export interface DocInfo {
  filename: string;
  year?: number;
  geography?: string;
  source_type?: string;
  experiments_count: number;
}

export interface Entity {
  type: string;
  value: string;
}

export interface Relation {
  source: string;
  type: string;
  target: string;
}

export interface Experiment {
  id: string;
  name: string;
  input_entities: Entity[];
  process_entities: Entity[];
  output_entities: Entity[];
  relations: Relation[];
  evidence: string[];
  confidence: number;
  year?: number;
  geography?: string;
  source_type?: string;
  is_sensitive: boolean;
}

export interface Gap {
  configuration: Entity[];
  similar_experiments: string[];
  predicted_properties: Entity[];
}

export interface EnrichedGap {
  configuration: Entity[];
  predicted_properties: Entity[];
  hypothesis: string;
}


export interface SearchResult {
  experiment: Experiment;
  similarity: number;
}

export interface Consensus {
  ratio: number;
  agree: number;
  contradict: number;
  total: number;
}

export interface Counterfactual {
  experiment: Experiment;
  difference: {
    parameter: string;
    from: string;
    to: string;
  };
  effects: {
    property: string;
    from: string;
    to: string;
  }[];
}

export interface AssistantPayload {
  markdown: string;
  results: SearchResult[];
  consensus: Consensus;
  counterfactual?: {
    base: Experiment;
    cf: Counterfactual;
  };
  live?: boolean;
}

export interface ChatMessage {
  id: number;
  kind: "user" | "assistant";
  text?: string;
  payload?: AssistantPayload;
}


export const ROLES = [
  { id: "Administrator", label: "Администратор", person: "И. И. Сидоров" },
  { id: "Analyst", label: "Аналитик", person: "А. Петрова" },
  { id: "Researcher", label: "Исследователь", person: "П. К. Смирнов" },
  { id: "External Partner", label: "Внешний партнёр", person: "John Doe" },
];

export interface GraphNode {
  id: string;
  label: string;
  group: string;
  title: string;
}

export interface GraphEdge {
  from: string;
  to: string;
  label?: string;
  arrows?: string;
  color?: any;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface IngestStatus {
  status: "idle" | "running" | "completed" | "failed";
  files_indexed: number;
  total_chunks: number;
  error: string | null;
}


