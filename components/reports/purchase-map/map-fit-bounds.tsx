"use client";

import { useEffect } from "react";
import { useMap } from "react-map-gl/mapbox";

type MapFitBoundsProps = {
  positions: [number, number][];
  boundsKey: string;
};

export function MapFitBounds({ positions, boundsKey }: MapFitBoundsProps) {
  const { current: map } = useMap();

  useEffect(() => {
    if (positions.length === 0 || !map) return;

    let minLat = Infinity;
    let maxLat = -Infinity;
    let minLng = Infinity;
    let maxLng = -Infinity;

    for (const [lat, lng] of positions) {
      minLat = Math.min(minLat, lat);
      maxLat = Math.max(maxLat, lat);
      minLng = Math.min(minLng, lng);
      maxLng = Math.max(maxLng, lng);
    }

    if (
      !Number.isFinite(minLat) ||
      !Number.isFinite(maxLat) ||
      !Number.isFinite(minLng) ||
      !Number.isFinite(maxLng)
    ) {
      return;
    }

    map.fitBounds(
      [
        [minLng, minLat],
        [maxLng, maxLat],
      ],
      { padding: 40, maxZoom: 12 }
    );
  }, [map, positions, boundsKey]);

  return null;
}
