"use client";

import { useEffect, useState } from "react";

import { getVersion, listVersions } from "@/features/entities/api";
import type { EntityAttribute } from "@/features/entities/types";

export type HeadAttributeLoad = {
  attributes: EntityAttribute[];
  failed: boolean;
  ready: boolean;
};

const IDLE: HeadAttributeLoad = { attributes: [], failed: false, ready: false };

export function useEntityHeadAttributes(entityId: string): HeadAttributeLoad {
  const [state, setState] = useState<HeadAttributeLoad & { entityId: string }>({
    entityId: "",
    ...IDLE,
  });

  useEffect(() => {
    if (!entityId) {
      setState({ entityId: "", ...IDLE });
      return;
    }
    let cancelled = false;
    setState({ entityId, ...IDLE });
    void listVersions(entityId, { limit: 50 })
      .then(async (page) => {
        const published = page.items
          .filter((item) => item.publish_status === "published")
          .sort((left, right) => right.version - left.version);
        const head = published[0];
        if (!head) {
          if (!cancelled) setState({ entityId, attributes: [], failed: false, ready: true });
          return;
        }
        const version = head.attributes
          ? head
          : (await getVersion(entityId, head.id)).version;
        if (!cancelled) {
          setState({
            entityId,
            attributes: version.attributes ?? [],
            failed: false,
            ready: true,
          });
        }
      })
      .catch(() => {
        if (!cancelled) setState({ entityId, attributes: [], failed: true, ready: false });
      });
    return () => {
      cancelled = true;
    };
  }, [entityId]);

  if (state.entityId !== entityId) return IDLE;
  return {
    attributes: state.attributes,
    failed: state.failed,
    ready: state.ready,
  };
}
