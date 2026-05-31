"use client";

import "mapbox-gl/dist/mapbox-gl.css";
import Map from "react-map-gl/mapbox";
import { MapFitBounds } from "@/components/reports/purchase-map/map-fit-bounds";
import { PurchaseMapLayers } from "@/components/reports/purchase-map/purchase-map-layers";
import type { MapEmployeePurchases } from "@/lib/types/map";

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN;

const DEFAULT_VIEW = {
  longitude: -96,
  latitude: 56,
  zoom: 4,
};

type PurchaseMapInnerProps = {
  employees: MapEmployeePurchases[];
  colorIndex: Map<string, number>;
  boundsKey: string;
};

export default function PurchaseMapInner({
  employees,
  colorIndex,
  boundsKey,
}: PurchaseMapInnerProps) {
  const positions: [number, number][] = [];
  for (const emp of employees) {
    for (const p of emp.points) {
      if (Number.isFinite(p.lat) && Number.isFinite(p.lng)) {
        positions.push([p.lat, p.lng]);
      }
    }
  }

  if (!MAPBOX_TOKEN) {
    return (
      <div className="flex h-full items-center justify-center px-4">
        <p className="text-center text-sm text-muted-foreground">
          Map unavailable: missing NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN.
        </p>
      </div>
    );
  }

  return (
    <Map
      mapboxAccessToken={MAPBOX_TOKEN}
      mapStyle="mapbox://styles/mapbox/light-v11"
      initialViewState={DEFAULT_VIEW}
      scrollZoom
      style={{ width: "100%", height: "100%" }}
    >
      <MapFitBounds positions={positions} boundsKey={boundsKey} />
      <PurchaseMapLayers employees={employees} colorIndex={colorIndex} />
    </Map>
  );
}
