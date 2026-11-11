export type HostSpan = "hour" | "day" | "retained";

export type HostSample = {
  t: string;
  v: number | null;
};

export type HostBytes = {
  used_bytes: number | null;
  total_bytes: number | null;
};

export type FilesystemTile = HostBytes & {
  mount: string;
  type: string;
  used_share: number | null;
  free_inodes: number | null;
};

export type FilesystemChart = {
  mount: string;
  type: string;
  available: HostSample[];
  delta: HostSample[];
};

export type DiskChart = {
  device: string;
  busy_share: HostSample[];
  queue_length: HostSample[];
};

export type PressureSide = {
  waiting: HostSample[];
  stalled: HostSample[];
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
    memory: HostBytes;
    swap: HostBytes;
    filesystems: FilesystemTile[];
  };
  charts: {
    cpu_modes: { mode: string; samples: HostSample[] }[];
    run_queue: HostSample[];
    filesystems: FilesystemChart[];
    disks: DiskChart[];
    pressure: {
      cpu: PressureSide;
      memory: PressureSide;
      io: PressureSide;
    };
  };
};
