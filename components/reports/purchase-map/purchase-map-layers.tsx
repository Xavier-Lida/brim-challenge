"use client";

import { Fragment, useState } from "react";
import { Layer, Marker, Popup, Source } from "react-map-gl/mapbox";
import { Badge } from "@/components/ui/badge";
import { formatCad } from "@/lib/format/currency";
import { getEmployeeColor } from "@/lib/map/colors";
import { ColoredPin } from "@/lib/map/icons";
import type { MapEmployeePurchases } from "@/lib/types/map";

type PurchaseMapLayersProps = {
  employees: MapEmployeePurchases[];
  colorIndex: Map<string, number>;
};

export function PurchaseMapLayers({
  employees,
  colorIndex,
}: PurchaseMapLayersProps) {
  const [openPopupId, setOpenPopupId] = useState<string | null>(null);

  return (
    <>
      {employees.map((emp) => {
        const idx = colorIndex.get(emp.employee_id) ?? 0;
        const color = getEmployeeColor(idx);
        const segmentSourceId = `segments-${emp.employee_id}`;

        return (
          <Fragment key={emp.employee_id}>
            {emp.segments.length > 0 && (
              <Source
                id={segmentSourceId}
                type="geojson"
                data={{
                  type: "FeatureCollection",
                  features: emp.segments.map((seg) => ({
                    type: "Feature",
                    properties: {},
                    geometry: {
                      type: "LineString",
                      coordinates: [
                        [seg.from.lng, seg.from.lat],
                        [seg.to.lng, seg.to.lat],
                      ],
                    },
                  })),
                }}
              >
                <Layer
                  id={`${segmentSourceId}-line`}
                  type="line"
                  paint={{
                    "line-color": color,
                    "line-width": 3,
                    "line-opacity": 0.65,
                    "line-dasharray": [2, 1.5],
                  }}
                />
              </Source>
            )}
            {emp.points.map((point) => (
              <Fragment key={point.transaction_id}>
                <Marker
                  longitude={point.lng}
                  latitude={point.lat}
                  anchor="bottom"
                  onClick={(event) => {
                    event.originalEvent.stopPropagation();
                    setOpenPopupId(point.transaction_id);
                  }}
                >
                  <ColoredPin color={color} />
                </Marker>
                {openPopupId === point.transaction_id && (
                  <Popup
                    longitude={point.lng}
                    latitude={point.lat}
                    anchor="bottom"
                    offset={12}
                    closeButton
                    closeOnClick={false}
                    onClose={() => setOpenPopupId(null)}
                  >
                    <div className="min-w-[180px] space-y-1.5 text-sm">
                      <p className="font-medium">{point.merchant_name}</p>
                      <p className="text-muted-foreground">{point.city}</p>
                      <p>{formatCad(point.amount)}</p>
                      <p className="text-muted-foreground">{point.date}</p>
                      <p className="text-xs text-muted-foreground">
                        {point.merchant_category}
                      </p>
                      {point.flag_count > 0 && (
                        <Badge variant="destructive" className="mt-1">
                          Flagged ({point.flag_count})
                        </Badge>
                      )}
                    </div>
                  </Popup>
                )}
              </Fragment>
            ))}
          </Fragment>
        );
      })}
    </>
  );
}
