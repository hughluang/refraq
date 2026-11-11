export type HostSpan = "hour" | "day" | "retained";

export type HostSample = {
  t: string;
  v: number | null;
};

export type HostRead = {
  span: HostSpan;
  start: string;
  end: string;
  step_seconds: number;
  tiles: {
    cpu: {
      online_count: number | null;
      busy_share: number | null;
    };
  };
  charts: {
    cpu_modes: { mode: string; samples: HostSample[] }[];
    run_queue: HostSample[];
  };
};
